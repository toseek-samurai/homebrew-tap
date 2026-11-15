#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync_preview', ROOT / 'tools/sync_preview.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

RECIPE = '''class ShinContextEngine < Formula
  url "https://github.com/toseek-samurai/shin-context-engine/archive/refs/tags/v1.0.0-dev.1.tar.gz"
  version "1.0.0-dev.1"
  sha256 "old-source"
  depends_on "sqlite"

  resource "shin_httplib" do
    url "https://github.com/example/http/archive/refs/tags/v1.tar.gz"
    sha256 "old-resource"
  end

  def install
    resources.each { |r| r.stage }
    system "cmake", "--build", "build"
  end

  service do
    run [opt_bin/"shin-ce", "serve", "--registered"]
  end

  test do
    refute_path_exists bin/"shin-updater"
  end
end
'''


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'Formula').mkdir()
        (self.root / 'Formula/shin-context-engine.rb').write_text(RECIPE)
        self.tag = 'v1.0.0-dev.2'
        self.sha = 'a' * 40
        self.marker = {'schema_version': 'shin.preview-platform.v1', 'repository': sync.REPO,
                       'platform': 'macos', 'version': self.tag[1:], 'core_version': '1.0.0-dev.3',
                       'source_sha': self.sha, 'run_id': 101, 'attempt': 1,
                       'assets': {name: 'sha256:' + 'b' * 64 for name in (
                           f'shin-local-{self.tag[1:]}-macos-arm64.zip',
                           f'shin-local-{self.tag[1:]}-macos-arm64.zip.sha256',
                           'shin-updater-v1-macos-arm64.zip', 'shin-updater-v1-macos-arm64.zip.sha256', 'install.sh')}}
        self.release = {'tag_name': self.tag, 'draft': False, 'prerelease': True,
                        'assets': [{'name': n} for n in [*self.marker['assets'], 'shin-preview-macos.json']]}
        self.archive = self.make_archive()

    def make_archive(self, libuv=True, invalid_pin=False):
        files = {'VERSION': self.marker['core_version'], 'observer/VERSION': self.tag[1:],
                 'docs/machine/shin-development-v1.json': json.dumps({'developmentLane': {
                     'coreVersion': self.marker['core_version'], 'observerSourceVersion': self.tag[1:]}})}
        for path, names in sync.CMAKE.items():
            if not libuv and path.endswith('Coordinator.cmake'):
                continue
            files[path] = ''.join(f'FetchContent_Declare({name}\n'
                                 f' URL https://codeload.github.com/example/{name}/tar.gz/refs/tags/v1\n'
                                 ' URL_HASH SHA256=' + ('bad' if invalid_pin else 'c' * 64) + ')\n' for name in names)
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            for name, value in files.items():
                item = tarfile.TarInfo('synthetic-source/' + name)
                raw = value.encode(); item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
        return data.getvalue()

    def fetch(self, url, limit):
        if url == sync.API + '/releases?per_page=30':
            value = [self.release]
        elif url.endswith('/shin-preview-macos.json'):
            value = self.marker
        elif '/git/ref/tags/' in url:
            value = {'object': {'type': 'tag', 'sha': 'd' * 40}}
        elif '/git/tags/' in url:
            value = {'object': {'type': 'commit', 'sha': self.sha}}
        elif url.endswith('.tar.gz'):
            return self.archive
        else:
            self.fail(url)
        return json.dumps(value).encode()

    def test_qualified_recipe_updates_all_pins_and_preserves_installation(self):
        output = self.root / 'candidate'
        result = sync.prepare(self.root, output, fetch=self.fetch)
        recipe, metadata = sync.candidate_files(output, result['formula_sha256'])
        text = recipe.decode()
        self.assertEqual(sync.version_of(text), self.tag[1:])
        self.assertEqual(metadata['source_sha256'], hashlib.sha256(self.archive).hexdigest())
        self.assertEqual(set(metadata['resources']), sync.KNOWN)
        self.assertIn('LICENSE-extra', text)
        self.assertIn('  depends_on "sqlite"', text)
        self.assertIn(RECIPE[RECIPE.index('  def install'):RECIPE.index('  test do')], text)
        self.assertIn('refute_path_exists bin/"shin-updater"', text)
        self.assertEqual((self.root / 'Formula/shin-context-engine.rb').read_text(), RECIPE)

    def test_pending_platform_or_draft_does_not_advance_recipe(self):
        for change in ({'draft': True}, {'assets': []}, {'prerelease': False}):
            with self.subTest(change=change):
                previous = copy.deepcopy(self.release); self.release.update(change)
                output = self.root / 'candidate'
                self.assertIsNone(sync.prepare(self.root, output, fetch=self.fetch))
                self.assertFalse(output.exists())
                self.release = previous

    def test_tag_and_receipt_must_identify_the_same_source(self):
        self.marker['source_sha'] = 'e' * 40
        with self.assertRaisesRegex(ValueError, 'qualified source'):
            sync.prepare(self.root, self.root / 'candidate', fetch=self.fetch)

    def test_dependency_hash_failure_preserves_current_recipe(self):
        self.archive = self.make_archive(invalid_pin=True)
        with self.assertRaisesRegex(ValueError, 'pin'):
            sync.prepare(self.root, self.root / 'candidate', fetch=self.fetch)
        self.assertEqual((self.root / 'Formula/shin-context-engine.rb').read_text(), RECIPE)

    def test_source_versions_must_match_the_qualified_receipt(self):
        self.marker['core_version'] = '1.0.0-dev.4'
        output = self.root / 'candidate'
        with self.assertRaisesRegex(ValueError, 'component versions'):
            sync.prepare(self.root, output, fetch=self.fetch)
        self.assertFalse(output.exists())

    def test_concurrent_tap_edit_refuses_promotion_before_network_or_writes(self):
        output = self.root / 'candidate'
        result = sync.prepare(self.root, output, fetch=self.fetch)
        repo = self.root / 'tap'
        (repo / 'Formula').mkdir(parents=True)
        (repo / '.github').mkdir()
        recipe = repo / 'Formula/shin-context-engine.rb'
        recipe.write_text(RECIPE)

        def git(*args):
            return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()

        git('init', '--quiet', '--initial-branch=main')
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'base')
        base = git('rev-parse', 'HEAD')
        git('update-ref', 'refs/remotes/origin/main', base)
        (repo / 'README.md').write_text('Concurrent maintainer change\n')
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'owner edit')
        run = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/sync_preview.py'), 'apply',
                              '--root', str(repo), '--candidate', str(output), '--sha256', result['formula_sha256'],
                              '--base', base], capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('Tap changed', run.stderr)
        self.assertEqual(recipe.read_text(), RECIPE)
        self.assertFalse((repo / '.github/upstream-preview.json').exists())
        self.assertEqual(git('status', '--porcelain'), '')

    def test_older_qualified_source_need_not_have_libuv(self):
        self.archive = self.make_archive(libuv=False)
        result = sync.prepare(self.root, self.root / 'candidate', fetch=self.fetch)
        self.assertNotIn('shin_libuv', result['resources'])

    def test_tampered_artifact_and_downgrade_are_refused(self):
        output = self.root / 'candidate'; result = sync.prepare(self.root, output, fetch=self.fetch)
        with (output / 'shin-context-engine.rb').open('a') as file:
            file.write('\n# changed after qualification\n')
        with self.assertRaisesRegex(ValueError, 'identity'):
            sync.candidate_files(output, result['formula_sha256'])
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            sync.render(RECIPE, '1.0.0-dev.1', 'f' * 64, {})


if __name__ == '__main__':
    unittest.main()
