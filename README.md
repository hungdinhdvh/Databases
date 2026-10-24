# Database Docker Environment

This project provides a Docker Compose setup with multiple databases for development and testing purposes.

## Included Databases

- **MySQL** 8.0
- **MongoDB** 6.0
- **PostgreSQL** 15
- **Redis** 7

## Quick Start

### 0. Configure the environment (first setup only)

```bash
# Skip this copy when .env already exists.
cp .env.example .env
chmod 600 .env
```

Edit `.env` for credentials and host ports. `.env` and `backups/` are ignored by
Git; `.env.example` contains only local development defaults. Compose reads
`.env` automatically. Shell environment variables can override these values.
Keep MySQL/PostgreSQL database names and usernames nonempty.

Existing volumes keep their original users and passwords. Editing `.env`
does **not** rotate credentials: change them inside the database first, then
update `.env` and recreate the affected container. Do not delete volumes to
change passwords. Connection examples below use the sample defaults.

### 1. Start All Databases

```bash
docker compose up -d --wait --wait-timeout 180
```

The start command waits until all four healthchecks pass. First startup may
take longer while Docker downloads the images.

### 2. Check Status

```bash
docker compose ps
```

### 3. Stop All Databases

```bash
docker compose down
```

### 4. Stop and Remove Volumes (Warning: Deletes all data)

```bash
docker compose down -v
```

---

## Connection Details

### MySQL

- **Host:** `localhost`
- **Port:** `13306`
- **Database:** `mydb`
- **Username:** `admin`
- **Password:** `admin123`
- **Root Password:** `rootpassword`
- **Privileges:** `ALL PRIVILEGES ON *.*` (development only)

**Connection Example:**
```bash
mysql --protocol=TCP -h 127.0.0.1 -P 13306 -u admin -p mydb
```

**Connection String:**
```
mysql://admin:admin123@localhost:13306/mydb
```

**Important:**
The global grant for the configured `MYSQL_USER` (default `admin`) is applied by `mysql-init/01-admin-grants.sh`
only when MySQL initializes an empty data directory. For an existing volume,
apply it without deleting data (the container must be running):

```bash
docker compose exec -T mysql sh /docker-entrypoint-initdb.d/01-admin-grants.sh
```

Do not use `docker compose down -v` to fix permissions: it deletes the data
volumes for **all four databases**.

---

### MongoDB

- **Host:** `localhost`
- **Port:** `27018`
- **Username:** `admin`
- **Password:** `admin123`

**Connection Example:**
```bash
mongosh "mongodb://admin:admin123@localhost:27018/?authSource=admin"
```

**Connection String:**
```
mongodb://admin:admin123@localhost:27018/?authSource=admin
```

---

### PostgreSQL

- **Host:** `localhost`
- **Port:** `15432`
- **Database:** `mydb`
- **Username:** `admin`
- **Password:** `admin123`

**Connection Example:**
```bash
psql -h localhost -p 15432 -U admin -d mydb
```

**Connection String:**
```
postgresql://admin:admin123@localhost:15432/mydb
```

---

### Redis

- **Host:** `localhost`
- **Port:** `16379`
- **Password:** None (for development only)

**Connection Example:**
```bash
redis-cli -h localhost -p 16379
```

**Connection String:**
```
redis://localhost:16379
```

---

## Programmatic Connection Examples

### Node.js

```javascript
// MySQL
const mysql = require('mysql2');
const mysqlConn = mysql.createConnection({
  host: 'localhost',
  port: 13306,
  user: 'admin',
  password: 'admin123',
  database: 'mydb'
});

// MongoDB
const { MongoClient } = require('mongodb');
const mongoClient = new MongoClient('mongodb://admin:admin123@localhost:27018/?authSource=admin');

// PostgreSQL
const { Pool } = require('pg');
const pgPool = new Pool({
  host: 'localhost',
  port: 15432,
  user: 'admin',
  password: 'admin123',
  database: 'mydb'
});

// Redis
const redis = require('redis');
const redisClient = redis.createClient({ url: 'redis://localhost:16379' });
```

### Python

```python
import mysql.connector
from pymongo import MongoClient
import psycopg2
import redis

# MySQL
mysql_conn = mysql.connector.connect(
    host='localhost',
    port=13306,
    user='admin',
    password='admin123',
    database='mydb'
)

# MongoDB
mongo_client = MongoClient('mongodb://admin:admin123@localhost:27018/?authSource=admin')

# PostgreSQL
pg_conn = psycopg2.connect(
    host='localhost',
    port=15432,
    user='admin',
    password='admin123',
    database='mydb'
)

# Redis
redis_client = redis.Redis(host='localhost', port=16379)
```

---

## Useful Commands

### View Logs

```bash
# All databases
docker compose logs -f

# Specific database
docker compose logs -f mysql
docker compose logs -f mongodb
docker compose logs -f postgresql
docker compose logs -f redis
```

### Access Database Containers

```bash
docker exec -it mysql_db bash
docker exec -it mongodb bash
docker exec -it postgresql_db bash
docker exec -it redis_cache sh
```

---

## Notes

- Database files are stored in named Docker volumes, preserved by `docker compose down` without `-v`.
- Redis uses AOF with `appendfsync everysec`; an abrupt crash can still lose roughly the last second of writes. Volumes are not backups.
- Published ports bind to `127.0.0.1` for local development; use `127.0.0.1` explicitly if `localhost` resolves to IPv6.
- Credentials above are development defaults, stored in `.env`. Redis has no password.
- Changing initialization credentials in Compose does not update users in an existing database volume.
- For production use, change default passwords and configure security settings
- All databases are on the same network (`db_network`) for inter-container communication
- Default credentials are for development only


## Container-to-container connections

Applications attached to this project's `db_network` use service names and
internal ports, not the published host ports:

| Service | Host | Port |
| --- | --- | --- |
| MySQL | `mysql` | `3306` |
| MongoDB | `mongodb` | `27017` |
| PostgreSQL | `postgresql` | `5432` |
| Redis | `redis` | `6379` |

MongoDB connections with the root account require `authSource=admin`.
MongoDB creates an application database when you first write data to it.

## Verify database access

These commands use the clients bundled in the containers:

```bash
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql --protocol=TCP -h 127.0.0.1 -u "$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT 1; SHOW GRANTS FOR CURRENT_USER;"'
docker compose exec -T mongodb sh -c 'mongosh --quiet --host 127.0.0.1 -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "db.adminCommand({ping: 1})"'
docker compose exec -T postgresql sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT 1;"'
docker compose exec -T redis redis-cli ping
```

References: [Compose healthchecks](https://docs.docker.com/reference/compose-file/services/#healthcheck),
[Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/).


## Backup and restore

Requirements: Docker Compose and Python 3.9+ on macOS/Linux. Run from this
project folder. No Python packages or database clients need installing.

### Create a backup

```bash
python3 scripts/db_tools.py backup
```

This is a **cold, full-volume backup**: stop applications that write to these
databases, then run the command. It briefly stops all four databases, archives
all data and database accounts, and starts all four again, waiting for healthchecks.
It creates a timestamped directory in `backups/` containing four `.tar.gz`
archives and a manifest with image IDs and SHA-256 checksums. Normal backup
errors trigger a restart attempt. An interrupted Docker connection or killed
process may require `docker compose start --wait --wait-timeout 180` manually.

The script prints the exact backup path. To validate it without changing Docker:

```bash
python3 scripts/db_tools.py verify backups/REPLACE_WITH_BACKUP_DIRECTORY
```

Backups stay on this computer; copy them to another disk if you need protection
against disk loss. They contain sensitive data and are not encrypted. `.env`
is deliberately excluded: store its matching credentials separately and securely.
Incomplete runs leave `.partial-*` directories; these are not completed backups.

### Restore a trusted backup

Restore **replaces all data in all four current database volumes**. Stop
applications writing to the databases first. Use the same database images and
architecture as the backup, and credentials matching the accounts in that backup.
The tool refuses mismatched image IDs. This is recovery, not a version migration.

```bash
python3 scripts/db_tools.py verify backups/REPLACE_WITH_BACKUP_DIRECTORY
python3 scripts/db_tools.py restore backups/REPLACE_WITH_BACKUP_DIRECTORY --confirm
```

The tool checks every archive before stopping databases. It then creates a
`*-before-restore-*` backup of the current volumes before replacing anything.
Keep that directory to undo a restore using the same restore command. If
extraction fails, databases are left stopped; resolve the error and restore
from the printed recovery path. If Docker itself becomes unavailable, confirm
all services are stopped before trying recovery.

All four containers must already exist. On a new machine, prepare `.env`, use
the image IDs in `manifest.json` (the original images must be available), and
initialize the stack before restoring. Do not use `down -v` as part of recovery.
Backups validate checksums, not authenticity: use only backups you trust.
External tablespaces, extra mounts, symlinks and special files are outside this
backup format; validation rejects them. The MySQL runtime socket symlink is
excluded because the server recreates it.

### Tests

```bash
# Fast validation tests; no Docker access or database changes.
python3 -m unittest discover -s tests -v

# Explicit integration test: pauses/restarts this stack; restores only to
# a separate temporary project with no published ports, then removes it.
python3 tests/integration_db_tools.py
```

The integration test writes uniquely named test records, verifies persistence
after restart, verifies backup/restore and recovery from the automatic safety
backup, then removes its test records and temporary project. Run it when local
applications can tolerate a short interruption.

Implementation references: [Docker volume backup/restore](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes),
[Compose environment interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).
