#!/usr/bin/env python3
"""Prepare a source-pinned recipe only from a published, macOS-qualified preview."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request

REPO = 'toseek-samurai/shin-context-engine'
API = 'https://api.github.com/repos/' + REPO
PREVIEW = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-dev\.(?:0|[1-9][0-9]*)'
HEX = r'[0-9a-f]{64}'
CMAKE = {
    'observer/cmake/ClientConfig.cmake': {'shin_toml', 'shin_yaml'},
    'shared/cmake/Ftxui.cmake': {'shin_ftxui'},
    'shared/cmake/Mcp.cmake': {'shin_mcp'},
    'observer/tray/CMakeLists.txt': {'shin_imgui'},
    'shared/cmake/SecretScanner.cmake': {'shin_re2', 'shin_abseil'},
    'shared/cmake/Coordinator.cmake': {'shin_libuv'},
    'shared/cmake/SQLite.cmake': {'shin_sqlite'},
}
RETIRED = {'shin_httplib'}
KNOWN = set().union(*CMAKE.values()) | RETIRED
FILES = {'shin-context-engine.rb', 'upstream-preview.json'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def identity(version):
    require(re.fullmatch(PREVIEW, version), 'Expected a canonical preview version')
    return tuple(int(x) for x in re.split(r'\.|-dev\.', version))


def version_of(recipe):
    values = re.findall(r'^  version "([^"]+)"$', recipe, re.M)
    require(len(values) == 1, 'Recipe must declare one explicit preview version')
    identity(values[0])
    return values[0]


def download(url, limit):
    headers = {'User-Agent': 'shin-homebrew-sync', 'Accept': 'application/vnd.github+json', 'Cache-Control': 'no-cache'}
    token = os.environ.get('GH_TOKEN')
    if token and url.startswith(API + '/'):
        headers['Authorization'] = 'Bearer ' + token
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                data = response.read(limit + 1)
            require(len(data) <= limit, 'Upstream response exceeds its bound')
            return data
        except urllib.error.HTTPError as error:
            # The built-in token owns this tap, not the upstream repository.
            # Its public GETs need no extra credential if installation scope refuses them.
            if error.code in (403, 404) and 'Authorization' in headers and attempt < 2:
                del headers['Authorization']
                continue
            if error.code in (408, 429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise ValueError(f'Upstream read failed (HTTP {error.code}); existing formula is preserved') from None
        except urllib.error.URLError:
            if attempt == 2:
                raise ValueError('Upstream network read failed; existing formula is preserved') from None
            time.sleep(attempt + 1)
    raise ValueError('Upstream read attempts exhausted')


def json_at(url, fetch):
    return json.loads(fetch(url, 2 * 1024 * 1024))


def qualified(release, fetch):
    tag = release.get('tag_name', '')
    require(re.fullmatch('v' + PREVIEW, tag), 'Release has an invalid preview tag')
    if release.get('draft') or not release.get('prerelease'):
        return None
    names = {a['name'] for a in release.get('assets', [])}
    expected = {f'shin-local-{tag[1:]}-macos-arm64.zip', f'shin-local-{tag[1:]}-macos-arm64.zip.sha256',
                'shin-updater-v1-macos-arm64.zip', 'shin-updater-v1-macos-arm64.zip.sha256', 'install.sh'}
    if not expected | {'shin-preview-macos.json'} <= names:
        return None
    marker = json_at(f'https://github.com/{REPO}/releases/download/{tag}/shin-preview-macos.json', fetch)
    require(marker.get('schema_version') == 'shin.preview-platform.v1' and marker.get('repository') == REPO and
            marker.get('platform') == 'macos' and marker.get('version') == tag[1:],
            'Published macOS qualification identity differs')
    require(isinstance(marker.get('run_id'), int) and marker['run_id'] > 0 and
            isinstance(marker.get('attempt'), int) and marker['attempt'] > 0 and
            re.fullmatch(r'[0-9a-f]{40}', marker.get('source_sha', '')),
            'Published macOS qualification lacks source/run proof')
    require(set(marker.get('assets', {})) == expected and all(
        re.fullmatch('sha256:' + HEX, value) for value in marker['assets'].values()),
        'Published macOS qualification has incomplete asset digests')
    obj = json_at(f'{API}/git/ref/tags/{tag}', fetch)['object']
    for _ in range(3):
        if obj.get('type') != 'tag':
            break
        require(re.fullmatch(r'[0-9a-f]{40}', obj.get('sha', '')), 'Invalid annotated tag identity')
        obj = json_at(f'{API}/git/tags/{obj["sha"]}', fetch)['object']
    require(obj.get('type') == 'commit' and obj.get('sha') == marker['source_sha'],
            'Tag differs from the qualified source commit')
    return marker


def source_files(data):
    wanted = set(CMAKE) | {'VERSION', 'observer/VERSION', 'docs/machine/shin-development-v1.json'}
    files = {}
    total = 0
    prefix = None
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for count, member in enumerate(archive, 1):
            total += max(0, member.size)
            require(count <= 10000 and total <= 512 * 1024 * 1024, 'Source archive exceeds its bound')
            parts = member.name.split('/')
            require(not member.name.startswith('/') and '..' not in parts and parts[0], 'Unsafe source archive path')
            if prefix is None:
                prefix = parts[0]
            require(parts[0] == prefix, 'Source archive has multiple roots')
            name = member.name.partition('/')[2]
            if name not in wanted:
                continue
            require(member.isfile() and member.size <= 1024 * 1024 and name not in files,
                    'Selected source metadata is not one bounded regular file')
            files[name] = archive.extractfile(member).read().decode('utf-8')
    require(wanted - {'shared/cmake/Coordinator.cmake'} <= files.keys(), 'Source metadata is incomplete')
    return files


def resources(files, fetch=download):
    pins = {}
    for path, required in CMAKE.items():
        if path not in files:
            continue  # Older qualified previews predate the coordinator dependency.
        text = re.sub(r'#[^\n]*', '', files[path])
        found = set()
        for name, body in re.findall(r'FetchContent_Declare\s*\(\s*(shin_[a-z0-9_]+)\b(.*?)\)', text, re.S | re.I):
            url = re.search(r'\bURL\s+(\S+)', body)
            sha = re.search(r'\bURL_HASH\s+(SHA256|SHA3_256)=(' + HEX + r')\b', body)
            require(url is not None and sha is not None and name not in pins, 'Dependency pin is missing or ambiguous')
            if name == 'shin_sqlite':
                require(sha[1] == 'SHA3_256' and re.fullmatch(
                    r'https://www.sqlite.org/[0-9]{4}/sqlite-amalgamation-[0-9]{7}\.zip', url[1]),
                    'SQLite must use its official pinned SHA3-256 archive')
                data = fetch(url[1], 16 * 1024 * 1024)
                require(len(data) <= 16 * 1024 * 1024 and hashlib.sha3_256(data).hexdigest() == sha[2],
                        'SQLite archive digest differs from the qualified source pin')
                pins[name] = {'url': url[1], 'sha256': hashlib.sha256(data).hexdigest()}
                found.add(name)
                continue
            require(sha[1] == 'SHA256', 'GitHub dependencies require an immutable SHA-256 pin')
            match = re.fullmatch(r'https://codeload.github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/tar.gz/'
                                 r'(refs/tags/[A-Za-z0-9_.-]+|[0-9a-f]{40})', url[1])
            require(match is not None, 'Dependency must use a literal immutable GitHub reference')
            pins[name] = {'url': f'https://github.com/{match[1]}/archive/{match[2]}.tar.gz', 'sha256': sha[2]}
            found.add(name)
        require(required <= found, 'Required dependency declaration is missing')
    return pins


def render(recipe, version, sha, pins):
    require(identity(version) > identity(version_of(recipe)), 'Refuse a recipe downgrade or same-version rewrite')
    for pattern, replacement in [
            (r'^  url "[^"]+"$', f'  url "https://github.com/{REPO}/archive/refs/tags/v{version}.tar.gz"'),
            (r'^  version "[^"]+"$', f'  version "{version}"'),
            (r'^  sha256 "[^"]+"$', f'  sha256 "{sha}"')]:
        recipe, count = re.subn(pattern, replacement, recipe, flags=re.M)
        require(count == 1, 'Recipe header is ambiguous')
    start, end = recipe.index('  resource "'), recipe.index('  def install\n')
    old = set(re.findall(r'^  resource "([^"]+)" do$', recipe[start:end], re.M))
    require(old - pins.keys() <= KNOWN, 'An unknown maintained resource would be removed')
    blocks = ''.join(f'  resource "{name}" do\n    url "{pin["url"]}"\n'
                     f'    sha256 "{pin["sha256"]}"\n  end\n\n' for name, pin in sorted(pins.items()))
    recipe = recipe[:start] + blocks + recipe[end:]
    if 'shin_sqlite' in pins:
        dependency = '  depends_on "sqlite"\n'
        require(recipe.count(dependency) <= 1, 'System SQLite dependency is ambiguous')
        recipe = recipe.replace(dependency, '')
    notices = ''.join(f'    assert_path_exists share/"shin-observer/licenses/libuv/{name}"\n'
                      for name in ('LICENSE', 'LICENSE-extra'))
    recipe = recipe.replace(notices, '')
    if 'shin_libuv' in pins:
        anchor = '    refute_path_exists bin/"shin-updater"\n'
        require(recipe.count(anchor) == 1, 'Recipe notice-test anchor is missing')
        recipe = recipe.replace(anchor, notices + anchor)
    return recipe


def prepare(root, output, tag='', fetch=download):
    root, output = Path(root), Path(output)
    recipe = (root / 'Formula/shin-context-engine.rb').read_text()
    current = identity(version_of(recipe))
    if tag:
        require(re.fullmatch('v' + PREVIEW, tag), 'Invalid requested preview tag')
    releases = json_at(API + '/releases?per_page=30', fetch)
    require(isinstance(releases, list), 'Invalid release listing')
    releases = [r for r in releases if re.fullmatch('v' + PREVIEW, r.get('tag_name', '')) and
                (not tag or r['tag_name'] == tag) and identity(r['tag_name'][1:]) > current]
    for release in sorted(releases, key=lambda r: identity(r['tag_name'][1:]), reverse=True):
        marker = qualified(release, fetch)
        if marker is None:
            continue
        version = release['tag_name'][1:]
        url = f'https://github.com/{REPO}/archive/refs/tags/v{version}.tar.gz'
        data = fetch(url, 64 * 1024 * 1024)
        files = source_files(data)
        policy = json.loads(files['docs/machine/shin-development-v1.json'])['developmentLane']
        require(files['observer/VERSION'].strip() == version == policy['observerSourceVersion'] and
                files['VERSION'].strip() == marker['core_version'] == policy['coreVersion'],
                'Source component versions differ from the qualification receipt')
        # Check again after the archive download, before deriving an installable recipe.
        require(qualified(release, fetch) == marker, 'Qualification changed during preparation')
        pins = resources(files, fetch)
        sha = hashlib.sha256(data).hexdigest()
        candidate = render(recipe, version, sha, pins).encode()
        metadata = {'schema_version': 'shin.homebrew-preview.v1', 'repository': REPO, 'tag': 'v' + version,
                    'source_sha': marker['source_sha'], 'source_sha256': sha, 'core_version': marker['core_version'],
                    'macos_run_id': marker['run_id'], 'macos_attempt': marker['attempt'],
                    'formula_sha256': hashlib.sha256(candidate).hexdigest(), 'resources': pins}
        output.mkdir(parents=True, exist_ok=True)
        (output / 'shin-context-engine.rb').write_bytes(candidate)
        (output / 'upstream-preview.json').write_text(json.dumps(metadata, indent=2) + '\n')
        return metadata
    return None


def candidate_files(directory, expected):
    directory = Path(directory)
    require({p.name for p in directory.iterdir()} == FILES and all(
        p.is_file() and not p.is_symlink() and p.stat().st_size <= 65536 for p in directory.iterdir()),
        'Expected exactly the bounded candidate recipe and metadata')
    recipe = (directory / 'shin-context-engine.rb').read_bytes()
    metadata = json.loads((directory / 'upstream-preview.json').read_text())
    require(re.fullmatch(HEX, expected) and metadata.get('schema_version') == 'shin.homebrew-preview.v1' and
            metadata.get('repository') == REPO and hashlib.sha256(recipe).hexdigest() == expected == metadata.get('formula_sha256') and
            metadata.get('tag') == 'v' + version_of(recipe.decode()), 'Candidate recipe identity differs')
    return recipe, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'overlay', 'apply'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--tag', default='')
    parser.add_argument('--sha256', default='')
    parser.add_argument('--base', default='')
    args = parser.parse_args()
    if args.command == 'prepare':
        metadata = prepare(args.root, args.candidate, args.tag)
        fields = {'changed': 'true' if metadata else 'false',
                  'version': metadata['tag'][1:] if metadata else '',
                  'formula_sha256': metadata['formula_sha256'] if metadata else ''}
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
                out.write(''.join(f'{key}={value}\n' for key, value in fields.items()))
        print(json.dumps(fields))
        return
    recipe, metadata = candidate_files(args.candidate, args.sha256)
    if args.command == 'apply':
        require(re.fullmatch(r'[0-9a-f]{40}', args.base), 'Expected the tested tap base commit')
        git = lambda *v: subprocess.check_output(['git', '-C', str(args.root), *v], text=True).strip()
        require(git('rev-parse', 'HEAD') == git('rev-parse', 'origin/main') == args.base and
                not git('status', '--porcelain'), 'Tap changed while installation tests ran; retry from current main')
        require(identity(metadata['tag'][1:]) > identity(version_of((args.root / 'Formula/shin-context-engine.rb').read_text())),
                'Current formula is already newer; refuse stale promotion')
        release = json_at(API + '/releases/tags/' + metadata['tag'], download)
        proof = qualified(release, download)
        require(proof is not None and proof['source_sha'] == metadata['source_sha'] and
                proof['run_id'] == metadata['macos_run_id'] and proof['attempt'] == metadata['macos_attempt'],
                'Published qualification changed after the installation tests')
        shutil.copyfile(args.candidate / 'upstream-preview.json', args.root / '.github/upstream-preview.json')
    (args.root / 'Formula/shin-context-engine.rb').write_bytes(recipe)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, tarfile.TarError) as error:
        raise SystemExit('Preview synchronization refused: ' + str(error)[:512]) from None
