"""WP15 / addendum A10.4: test Redis is app-local; tests only use this machine's MySQL."""

from __future__ import annotations

from tests.conftest import mysql_host_is_local, mysql_test_url, redis_test_url


def test_r1_redis_url_wins() -> None:
    env = {"MSP_TEST_REDIS_URL": "redis://:x@10.0.0.9:6390/2", "MSP_TEST_MYSQL_HOST": "192.0.2.16"}
    assert redis_test_url(env) == "redis://:x@10.0.0.9:6390/2"


def test_r1_shared_mysql_keeps_redis_local() -> None:
    """The Hermes QA layout: MySQL on a shared server, nothing set for Redis -> this machine's compose Redis."""
    env = {"MSP_TEST_MYSQL_HOST": "192.0.2.16", "MSP_MYSQL_PORT": "3306"}
    assert redis_test_url(env) == "redis://:dev-redis-pw@127.0.0.1:6380/0"
    assert mysql_test_url("api", env) == "mysql+pymysql://msp_api:dev-api-pw@192.0.2.16:3306/msp"


def test_r1_redis_parts_and_password() -> None:
    env = {"MSP_TEST_MYSQL_HOST": "192.0.2.16", "MSP_TEST_REDIS_HOST": "192.0.2.20", "MSP_REDIS_PORT": "6381",
           "MSP_TEST_REDIS_PASSWORD": "pw"}  # fmt: skip
    assert redis_test_url(env) == "redis://:pw@192.0.2.20:6381/0"


def test_r1_defaults_are_the_local_stack() -> None:
    assert redis_test_url({}) == "redis://:dev-redis-pw@127.0.0.1:6380/0"
    assert mysql_test_url("migrator", {}) == "mysql+pymysql://msp_migrator:dev-migrator-pw@127.0.0.1:3307/msp"
    assert mysql_test_url("ingest", {"MSP_TEST_INGEST_PASSWORD": "s"}).startswith("mysql+pymysql://msp_ingest:s@")


def test_tests_refuse_a_remote_mysql() -> None:
    """Thomas 2026-11-20: throwaway test databases only on this machine's MySQL, never the live-data server."""
    assert mysql_host_is_local("127.0.0.1") and mysql_host_is_local("localhost")
    assert not mysql_host_is_local("192.0.2.16")
