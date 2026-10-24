#!/usr/bin/env python3
"""Cold volume backups for this local Docker Compose stack (Python 3.9+)."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
from datetime import datetime
import uuid

ROOT = Path(__file__).resolve().parents[1]
DATA_PATHS = {'mysql': '/var/lib/mysql', 'mongodb': '/data/db',
              'postgresql': '/var/lib/postgresql/data', 'redis': '/data'}


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def validate_backup(folder):
    """Reject incomplete, changed, or unsafe archives before any Docker mutation."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / 'manifest.json').read_text())
        if manifest.get('format') != 1 or set(manifest['services']) != set(DATA_PATHS):
            raise ValueError('Unsupported or incomplete backup manifest')
        for service in DATA_PATHS:
            archive = folder / f'{service}.tar.gz'
            entry = manifest['services'][service]
            if not entry['image_id'] or digest(archive) != entry['sha256']:
                raise ValueError(f'{service}: checksum mismatch')
            with tarfile.open(archive, 'r:gz') as source:
                count = 0
                for member in source:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                        raise ValueError(f'{service}: unsafe archive member {member.name!r}')
                    count += 1
                if not count:
                    raise ValueError(f'{service}: empty archive')
        return manifest
    except (OSError, KeyError, TypeError, AttributeError, tarfile.TarError) as exc:
        raise ValueError(f'Invalid backup: {exc}') from exc


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


class Stack:
    def __init__(self, compose_file, env_file):
        self.compose = ['docker', 'compose', '--env-file', str(env_file), '-f', str(compose_file)]
        self.containers = {}
        for service, destination in DATA_PATHS.items():
            ids = command(self.compose + ['ps', '-a', '-q', service], capture_output=True, text=True).stdout.split()
            if len(ids) != 1:
                raise ValueError(f'{service}: run docker compose up first (expected one container)')
            info = json.loads(command(['docker', 'inspect', ids[0]], capture_output=True, text=True).stdout)[0]
            mounts = [m for m in info['Mounts'] if m['Destination'] == destination and m['Type'] == 'volume']
            if len(mounts) != 1:
                raise ValueError(f'{service}: expected a named data volume')
            self.containers[service] = {'id': ids[0], 'volume': mounts[0]['Name'], 'image_id': info['Image']}
        self.helper_image = self.containers['redis']['image_id']

    def stop(self):
        command(self.compose + ['stop', '-t', '60'])
        for service, info in self.containers.items():
            state = json.loads(command(['docker', 'inspect', info['id']], capture_output=True, text=True).stdout)[0]['State']
            if state['Running'] or state['ExitCode'] != 0:
                raise ValueError(f'{service}: did not stop cleanly; refusing snapshot/restore')

    def start(self):
        command(self.compose + ['start', '--wait', '--wait-timeout', '180'])

    def helper(self, service, script, writable=False, **kwargs):
        mount = f'type=volume,src={self.containers[service]["volume"]},dst=/data'
        if not writable:
            mount += ',readonly'
        # No application entrypoint, network, host bind mount, or credentials.
        return command(['docker', 'run', '--rm', '-i', '--network', 'none', '--read-only',
                        '--mount', mount, '--entrypoint', 'sh', self.helper_image,
                        '-ec', script], **kwargs)


def snapshot(stack, backup_root, label='backup'):
    """Caller has stopped the stack. Partial directories are never valid backups."""
    name = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S%z') + '-' + label + '-' + uuid.uuid4().hex[:8]
    partial = backup_root / ('.partial-' + name)
    partial.mkdir(mode=0o700)
    manifest = {'format': 1, 'created_at': datetime.now().astimezone().isoformat(), 'services': {}}
    for service, info in stack.containers.items():
        print(f'Backing up {service}...', flush=True)
        archive = partial / f'{service}.tar.gz'
        with archive.open('xb') as dest:
            # MySQL's runtime socket symlink is not database content.
            stack.helper(service, 'tar -C /data --exclude=./mysql.sock -czf - .', stdout=dest)
        manifest['services'][service] = {'image_id': info['image_id'], 'sha256': digest(archive)}
    (partial / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    validate_backup(partial)
    final = backup_root / name
    partial.rename(final)
    print(f'Backup saved: {final}', flush=True)
    return final


def backup(stack, backup_root):
    try:
        stack.stop()
        return snapshot(stack, backup_root)
    finally:
        stack.start()


def restore(stack, folder, backup_root):
    manifest = validate_backup(folder)
    for service, info in stack.containers.items():
        if info['image_id'] != manifest['services'][service]['image_id']:
            raise ValueError(f'{service}: image differs from backup; use the original image first')
    try:
        stack.stop()
        recovery = snapshot(stack, backup_root, 'before-restore')
    except BaseException:
        stack.start()
        raise
    try:
        # All validation and the recovery snapshot complete before the first removal.
        for service in DATA_PATHS:
            print(f'Restoring {service}...', flush=True)
            with (folder / f'{service}.tar.gz').open('rb') as source:
                stack.helper(service,
                             'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar -C /data -xzpf -',
                             writable=True, stdin=source)
        stack.start()
    except BaseException:
        # Never start a partially restored collection of databases.
        stopped = subprocess.run(stack.compose + ['stop', '-t', '60'], check=False)
        state = 'Databases left stopped.' if stopped.returncode == 0 else 'Docker could not stop all services; stop them manually before recovery.'
        print(f'Restore failed. {state} Recovery backup: {recovery}', file=sys.stderr)
        raise
    print(f'Restore complete. Previous data is preserved at: {recovery}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compose-file', type=Path, default=ROOT / 'docker-compose.yml')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--backup-dir', type=Path, default=ROOT / 'backups')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('backup', help='Stop, snapshot all four volumes, then restart')
    check = sub.add_parser('verify', help='Check files, checksums and archive safety without Docker')
    check.add_argument('folder', type=Path)
    load = sub.add_parser('restore', help='Replace all four data volumes after a recovery backup')
    load.add_argument('folder', type=Path)
    load.add_argument('--confirm', action='store_true', help='Confirm replacement of current data')
    args = parser.parse_args()
    if args.action == 'restore' and not args.confirm:
        parser.error('Restore replaces all four databases. Review the backup and pass --confirm.')
    os.umask(0o077)
    if args.action == 'verify':
        validate_backup(args.folder)
        print('PASS: all four backup archives are complete and checksums match')
        return
    if args.action == 'restore':
        validate_backup(args.folder)  # Reject bad input before even contacting Docker.
    args.backup_dir = args.backup_dir.resolve()
    args.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (ROOT / '.db-maintenance.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stack = Stack(args.compose_file.resolve(), args.env_file.resolve())
        if args.action == 'backup':
            backup(stack, args.backup_dir)
        else:
            restore(stack, args.folder.resolve(), args.backup_dir)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
