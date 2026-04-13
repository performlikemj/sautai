import logging

from django.conf import settings
from django.db import connections
from django.db.models.signals import post_migrate
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_migrate)
def enable_rls_on_supabase_tables(sender, using, **kwargs):
    """Enable Row Level Security on any public tables that don't have it.

    Runs after each migrate on the supabase database. The django_service role
    bypasses RLS, so this only blocks access via the Supabase API/anon key.
    """
    if using != 'supabase':
        return

    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT schemaname, tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename NOT IN (
                  SELECT tablename FROM pg_tables
                  WHERE schemaname = 'public'
                    AND rowsecurity = true
              )
        """)
        tables = cursor.fetchall()

        for schema, table in tables:
            cursor.execute(
                f'ALTER TABLE "{schema}"."{table}" ENABLE ROW LEVEL SECURITY'
            )
            logger.info("Enabled RLS on %s.%s", schema, table)

    if tables:
        logger.info("Enabled RLS on %d table(s) after migrate.", len(tables))
