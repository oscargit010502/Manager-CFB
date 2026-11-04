#!/usr/bin/env python3
"""Create a private SQLite/document backup; stop writers before invoking."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone


def referenced_files(connection):
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, column in [('core_document', 'file'), ('core_company', 'logo')]:
        if table in tables:
            for (value,) in connection.execute(f'SELECT {column} FROM {table}'):
                if value:
                    path = Path(value)
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('La base contiene una ruta de documento inválida.')
                    yield Path('private') / path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'var')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--maintenance-confirmed', action='store_true', help='Confirma que la aplicación está detenida, sin escrituras ni cargas.')
    args = parser.parse_args()
    if not args.maintenance_confirmed:
        parser.error('Detenga la aplicación y confirme con --maintenance-confirmed para garantizar coherencia entre base y archivos.')
    data_dir = args.data_dir.resolve()
    database = data_dir / 'cfb.sqlite3'
    if not database.is_file() or database.is_symlink():
        parser.error('No se encontró una base SQLite regular en el directorio indicado.')
    output = args.output.absolute()
    if output.exists():
        parser.error('El archivo de destino ya existe; no se sobrescribirá.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cfb-backup-', dir=output.parent) as temp:
        stage = Path(temp)
        db_copy = stage / 'cfb.sqlite3'
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(db_copy) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('La base no superó la verificación de integridad.')
            for relative in referenced_files(target):
                if not (data_dir / relative).is_file():
                    raise ValueError(f'Falta un archivo referenciado: {relative}')
        paths = [(db_copy, 'cfb.sqlite3')]
        private = data_dir / 'private'
        if private.is_symlink():
            raise ValueError('El directorio privado no puede ser un enlace simbólico.')
        if private.exists():
            for path in sorted(private.rglob('*')):
                if path.is_symlink():
                    raise ValueError('No se permiten enlaces simbólicos dentro del almacenamiento privado.')
                if path.is_file():
                    paths.append((path, path.relative_to(data_dir).as_posix()))
        archive = stage / 'backup.zip'
        manifest = {'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'files': {}}
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for path, name in paths:
                digest = hashlib.sha256()
                size = 0
                with path.open('rb') as source, bundle.open(name, 'w', force_zip64=True) as target:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        target.write(chunk)
                manifest['files'][name] = {'size': size, 'sha256': digest.hexdigest()}
            bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.chmod(0o600)
        # Atomic publish without replacing an existing backup, including races.
        os.link(archive, output)
    print(f'Copia creada: {output} ({len(paths)} archivos). Guárdela cifrada fuera del servidor.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile) as exc:
        raise SystemExit(f'No se creó la copia: {exc}') from exc
