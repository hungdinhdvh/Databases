"""Opt-in real Docker test: restart live stack, restore only into disposable volumes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from db_tools import Stack


def call(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def query(compose, service, script, data=None):
    return call(compose + ['exec', '-T', service, 'sh', '-c', script], input=data,
                capture_output=True, text=True).stdout.strip()


MYSQL = 'MYSQL_PWD="$MYSQL_PASSWORD" mysql --protocol=TCP -h mysql -u "$MYSQL_USER" -N -B'
POSTGRES = 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h postgresql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -qAt'
MONGO = 'mongosh --quiet --host mongodb -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval '


def mongo(compose, js):
    import shlex
    return query(compose, 'mongodb', MONGO + shlex.quote(js))


def seed(compose, name):
    query(compose, 'mysql', MYSQL, f"CREATE DATABASE {name}; CREATE TABLE {name}.probe (id INT PRIMARY KEY, value VARCHAR(20)); INSERT INTO {name}.probe VALUES (1, 'persisted');")
    query(compose, 'postgresql', POSTGRES, f"CREATE TABLE {name} (id INT PRIMARY KEY, value TEXT); INSERT INTO {name} VALUES (1, 'persisted');")
    mongo(compose, f"db.getSiblingDB('{name}').probe.insertOne({{_id: 1, value: 'persisted'}})")
    assert query(compose, 'redis', f'redis-cli --raw SET {name} persisted NX') == 'OK'


def verify(compose, name, label):
    assert query(compose, 'mysql', MYSQL, f'SELECT value FROM {name}.probe WHERE id=1;') == 'persisted'
    assert query(compose, 'postgresql', POSTGRES, f'SELECT value FROM {name} WHERE id=1;') == 'persisted'
    assert mongo(compose, f"db.getSiblingDB('{name}').probe.findOne({{_id:1}}).value") == 'persisted'
    assert query(compose, 'redis', f'redis-cli --raw GET {name}') == 'persisted'
    print(f'PASS: {label} (all four databases)', flush=True)


def cleanup(compose, name):
    # Only objects with this run's random name are removed.
    query(compose, 'mysql', MYSQL, f'DROP DATABASE IF EXISTS {name};')
    query(compose, 'postgresql', POSTGRES, f'DROP TABLE IF EXISTS {name};')
    mongo(compose, f"db.getSiblingDB('{name}').dropDatabase()")
    query(compose, 'redis', f'redis-cli DEL {name}')


def escape_interpolation(value):
    if isinstance(value, str):
        return value.replace('$', '$$')
    if isinstance(value, list):
        return [escape_interpolation(v) for v in value]
    if isinstance(value, dict):
        return {k: escape_interpolation(v) for k, v in value.items()}
    return value


def main():
    token = uuid.uuid4().hex[:12]
    name = 'codex_probe_' + token
    project = 'db-restore-test-' + token
    stack = Stack(ROOT / 'docker-compose.yml', ROOT / '.env')
    compose = stack.compose
    with tempfile.TemporaryDirectory(prefix='db-restore-test-') as temp:
        folder = Path(temp)
        cfg = json.loads(call(compose + ['config', '--format', 'json'], capture_output=True, text=True).stdout)
        cfg['name'] = project
        for service, config in cfg['services'].items():
            config.pop('container_name', None)
            config.pop('ports', None)
            config['restart'] = 'no'
            config['image'] = stack.containers[service]['image_id']
        for kind in ('volumes', 'networks'):
            for key, config in cfg[kind].items():
                config['name'] = project + '_' + key
        test_file = folder / 'compose.json'
        test_file.write_text(json.dumps(escape_interpolation(cfg)))
        test_file.chmod(0o600)
        test_compose = ['docker', 'compose', '--env-file', str(ROOT / '.env'), '-f', str(test_file)]
        backups = folder / 'backups'
        tool = [sys.executable, str(ROOT / 'scripts/db_tools.py'), '--backup-dir', str(backups)]
        try:
            seed(compose, name)
            call(tool + ['backup'])
            source = next(p.parent for p in backups.glob('*/manifest.json'))
            call(tool + ['verify', str(source)])
            verify(compose, name, 'data survives backup stop/start')
            call(compose + ['restart', '-t', '60'])
            call(compose + ['up', '-d', '--wait', '--wait-timeout', '180'])
            verify(compose, name, 'data survives explicit restart')
            call(test_compose + ['up', '-d', '--wait', '--wait-timeout', '180'])
            # A distinct record must be restored by the automatic recovery backup.
            assert query(test_compose, 'redis', 'redis-cli SET before_restore original') == 'OK'
            call(tool + ['--compose-file', str(test_file), 'restore', str(source), '--confirm'])
            verify(test_compose, name, 'backup restored into isolated stack')
            assert query(test_compose, 'redis', 'redis-cli --raw GET before_restore') == ''
            recovery = next(p.parent for p in backups.glob('*before-restore*/manifest.json'))
            call(tool + ['--compose-file', str(test_file), 'restore', str(recovery), '--confirm'])
            assert query(test_compose, 'redis', 'redis-cli --raw GET before_restore') == 'original'
            assert query(test_compose, 'redis', f'redis-cli --raw GET {name}') == ''
            print('PASS: automatic pre-restore backup can recover previous data', flush=True)
        finally:
            call(test_compose + ['down', '-v'])
            cleanup(compose, name)


if __name__ == '__main__':
    main()
