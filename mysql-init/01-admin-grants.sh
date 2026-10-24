#!/bin/sh
set -eu
# Hex encoding keeps the configured username out of SQL syntax.
user_hex=$(printf '%s' "$MYSQL_USER" | od -An -tx1 | tr -d ' \n')
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root <<SQL
SET @account = CONVERT(0x${user_hex} USING utf8mb4);
SET @grant = CONCAT('GRANT ALL PRIVILEGES ON *.* TO ', QUOTE(@account), '@''%'' WITH GRANT OPTION');
PREPARE grant_statement FROM @grant;
EXECUTE grant_statement;
DEALLOCATE PREPARE grant_statement;
SQL
