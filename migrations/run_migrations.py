"""
Migration runner - executes all migrations in order.

Usage:
    python migrations/run_migrations.py
    python migrations/run_migrations.py --migration 001
    python migrations/run_migrations.py --migration 002
"""

import sys
import argparse
import importlib.util
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent


def run_migration(migration_name: str) -> bool:
    """Run a specific migration by name (e.g., '001_create_table')."""
    migration_file = MIGRATIONS_DIR / f"{migration_name}.py"
    
    if not migration_file.exists():
        print(f"✗ Migration file not found: {migration_file}")
        return False
    
    print(f"\n{'=' * 60}")
    print(f"Running migration: {migration_name}")
    print(f"{'=' * 60}\n")
    
    # Load and execute migration
    spec = importlib.util.spec_from_file_location(migration_name, migration_file)
    module = importlib.util.module_from_spec(spec)
    
    try:
        spec.loader.exec_module(module)
        
        # Check if migration has a run_migration function
        if hasattr(module, "run_migration"):
            return module.run_migration()
        else:
            # Migration should run on import (if __name__ == "__main__")
            print("⚠ Migration doesn't have run_migration() function")
            return True
            
    except Exception as e:
        print(f"✗ Error running migration {migration_name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def list_migrations():
    """List all available migrations."""
    migrations = sorted([
        f.stem for f in MIGRATIONS_DIR.glob("*.py")
        if f.stem.startswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9"))
        and f.stem != "__init__"
    ])
    
    print("Available migrations:")
    for migration in migrations:
        print(f"  - {migration}")
    return migrations


def main():
    parser = argparse.ArgumentParser(description="Run DynamoDB migrations")
    parser.add_argument(
        "--migration",
        type=str,
        help="Run specific migration (e.g., '001_create_table')",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available migrations",
    )
    
    args = parser.parse_args()
    
    if args.list:
        list_migrations()
        return
    
    if args.migration:
        # Run specific migration
        success = run_migration(args.migration)
        sys.exit(0 if success else 1)
    else:
        # Run all migrations in order
        migrations = list_migrations()
        
        if not migrations:
            print("No migrations found!")
            sys.exit(1)
        
        print(f"\nFound {len(migrations)} migration(s)")
        print("Running all migrations in order...\n")
        
        all_success = True
        for migration in migrations:
            success = run_migration(migration)
            all_success = all_success and success
            
            if not success:
                print(f"\n✗ Migration {migration} failed. Stopping.")
                break
        
        if all_success:
            print("\n" + "=" * 60)
            print("✓ All migrations completed successfully!")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("✗ Some migrations failed!")
            print("=" * 60)
        
        sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()

