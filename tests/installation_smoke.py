#!/usr/bin/env python3
"""Exercise an installed package with isolated source, clients and private state."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import sqlite3
import struct
import subprocess
import termios
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--prefix', type=Path, required=True)
parser.add_argument('--workspace', type=Path, required=True)
parser.add_argument('--phase', choices=('seed', 'verify'), required=True)
args = parser.parse_args()
base = args.workspace.resolve()
if args.phase == 'seed':
    base.mkdir(mode=0o700)
user, project, home = base/'user', base/'sample project', base/'state'
ce = args.prefix/'bin/shin-ce'
if args.phase == 'seed':
    user.mkdir(mode=0o700); project.mkdir(mode=0o700)
    (project/'sample.cpp').write_text('int readLimit() { return 17; }\n')
env = {**os.environ, 'HOME':str(user), 'PATH':'', 'LC_ALL':'C', 'TERM':'xterm-256color'}

def call(*words, error=None):
    process = subprocess.run([str(ce), *map(str, words), '--root', str(project), '--home', str(home)],
        env=env, capture_output=True, text=True, timeout=60)
    value = json.loads(process.stdout or process.stderr)
    if error:
        assert process.returncode == 2 and value.get('error',{}).get('code') == error, value
    else:
        assert process.returncode == 0 and value.get('ok'), value
    return value


def mcp_query():
    child = subprocess.Popen([str(args.prefix/'bin/shin-mcp'), '--root', str(project), '--home', str(home)],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sequence = 0
    pending = b''
    def rpc(method, params):
        nonlocal sequence, pending
        sequence += 1
        child.stdin.write((json.dumps({'jsonrpc':'2.0','id':sequence,'method':method,'params':params})+'\n').encode());child.stdin.flush()
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            while b'\n' in pending:
                line,pending=pending.split(b'\n',1);value=json.loads(line)
                if value.get('id') == sequence:
                    assert 'error' not in value,value
                    return value['result']
            ready,_,_=select.select([child.stdout],[],[],max(0,deadline-time.monotonic()))
            if ready:
                block=os.read(child.stdout.fileno(),8192)
                assert block,'MCP closed before response'
                pending+=block
        raise AssertionError('MCP response timeout')
    def tool(name, arguments):
        response=rpc('tools/call',{'name':name,'arguments':arguments})
        value=json.loads(response['content'][0]['text']);assert value.get('ok'),value
        return value
    try:
        initialized=rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'homebrew-smoke','version':'1'}})
        assert initialized['serverInfo']['name']=='shin'
        child.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n');child.stdin.flush()
        names={row['name'] for row in rpc('tools/list',{})['tools']}
        arguments={'query':'readLimit'}
        if 'shin_projects' in names:
            catalog=tool('shin_projects',{})
            arguments['project']=next(row['project'] for row in catalog['projects'] if row['root']==str(project))
        query=tool('shin_query',arguments)
        assert 'return 17' in query['source_context']
    finally:
        child.stdin.close();child.stdin=None
        child.communicate(timeout=15)
        assert child.returncode==0


def tui(language):
    master,slave=pty.openpty();fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',32,110,0,0))
    child=subprocess.Popen([str(ce),'stats','--home',str(home),'--language',language],env=env,
        stdin=slave,stdout=slave,stderr=slave,start_new_session=True);os.close(slave)
    frame=b'';deadline=time.monotonic()+8
    try:
        while time.monotonic()<deadline and child.poll() is None:
            ready,_,_=select.select([master],[],[],.1)
            if ready:
                frame+=os.read(master,65536)
                if len(frame)>1000: break
        assert len(frame)>1000,frame
        os.write(master,b'u');deadline=time.monotonic()+8
        while b'brew upgrade toseek-samurai/tap/shin-context-engine' not in frame and time.monotonic()<deadline:
            ready,_,_=select.select([master],[],[],.1)
            if ready: frame+=os.read(master,65536)
        assert b'brew upgrade toseek-samurai/tap/shin-context-engine' in frame,frame[-2000:]
        os.write(master,b'q');deadline=time.monotonic()+8
        while child.poll() is None and time.monotonic()<deadline:
            ready,_,_=select.select([master],[],[],.05)
            if ready:
                try: os.read(master,65536)
                except OSError: break
        child.wait(timeout=2);assert child.returncode==0
    finally:
        if child.poll() is None: child.kill();child.wait()
        os.close(master)

try:
    if args.phase == 'seed': call('init')
    else: call('service-start')
    query=call('query','readLimit');assert query['local_ready'] and 'return 17' in query['source_context']
    setup=call('mcp-config','--client','codex')
    assert setup['server']['command']==str(args.prefix/'bin/shin-mcp'),setup
    state=next((home/'projects').glob('*/state.json'))
    binding=json.loads(state.read_text())
    assert binding['profile_dir']==str(args.prefix/'share/shin-context/profiles'),binding
    config=user/'codex.toml'
    if args.phase=='seed':
        config.write_text('model = "keep-existing-setting"\n');config.chmod(0o600)
        review=call('client-connect','--client','codex','--config',config)
        call('client-connect','--client','codex','--config',config,'--revision',review['revision'])
    content=config.read_text()
    assert 'keep-existing-setting' in content and str(args.prefix/'bin/shin-mcp') in content
    mcp_query();tui('en');tui('ru')
    call('update-check',error='package-managed-installation')
    call('service-install',error='package-managed-service')
    assert not (args.prefix/'bin/shin-updater').exists()
    assert (args.prefix/'Shin Monitor.app/Contents/MacOS/Shin Monitor').is_file()
    baseline={'client_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),
        'source_sha256':hashlib.sha256((project/'sample.cpp').read_bytes()).hexdigest(),
        'profile_dir':binding['profile_dir'],'history_inode':(home/'service/history/telemetry.sqlite').stat().st_ino}
    if args.phase=='seed': (base/'baseline.json').write_text(json.dumps(baseline))
    else: assert baseline==json.loads((base/'baseline.json').read_text()),baseline
    with sqlite3.connect(f'file:{home}/service/history/telemetry.sqlite?mode=ro',uri=True) as db:
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    print(json.dumps({'ok':True,'phase':args.phase,'cli_query':True,'mcp_query':True,'tui_languages':['en','ru'],
        'stable_paths':True,'client_settings_preserved':True,'source_preserved':True,'native_update_refused':True,
        'homebrew_update_screen':True}))
finally:
    socket = home/'service/rpc.sock'
    if socket.exists():
        call('service-stop')
        deadline=time.monotonic()+15
        while socket.exists() and time.monotonic()<deadline: time.sleep(.05)
        assert not socket.exists(), 'Fixture service did not stop'
