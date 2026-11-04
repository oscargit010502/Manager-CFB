#!/usr/bin/env python3
"""Validate and restore a backup into a new directory; never replace live data."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
import zipfile


def safe_name(name):
    path = PurePosixPath(name)
    return (name == 'cfb.sqlite3' or (len(path.parts) >= 2 and path.parts[0] == 'private')) and not (
        path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or '\x00' in name or name != path.as_posix()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--data-dir', type=Path, required=True, help='Directorio nuevo; se rechazan destinos existentes.')
    parser.add_argument('--max-bytes', type=int, default=10 * 1024 ** 3, help='Límite de tamaño descomprimido, por defecto 10 GiB.')
    args = parser.parse_args()
    destination = args.data_dir.absolute()
    if destination.exists() or destination.is_symlink():
        parser.error('El destino ya existe; use un directorio nuevo.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cfb-restore-', dir=destination.parent) as temp:
        stage = Path(temp)
        with zipfile.ZipFile(args.archive) as bundle:
            infos = bundle.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or 'manifest.json' not in names:
                raise ValueError('Archivo duplicado o manifiesto ausente.')
            if bundle.getinfo('manifest.json').file_size > 16 * 1024 ** 2:
                raise ValueError('El manifiesto excede el tamaño permitido.')
            manifest = json.loads(bundle.read('manifest.json'))
            files = manifest.get('files', {})
            if manifest.get('version') != 1 or not isinstance(files, dict) or 'cfb.sqlite3' not in files:
                raise ValueError('Formato de copia no reconocido.')
            if set(names) != set(files) | {'manifest.json'}:
                raise ValueError('El contenido no coincide con el manifiesto.')
            if sum(info.file_size for info in infos) > args.max_bytes:
                raise ValueError('La copia supera el límite descomprimido.')
            for name, metadata in files.items():
                info = bundle.getinfo(name)
                mode = info.external_attr >> 16
                if not safe_name(name) or info.is_dir() or stat.S_ISLNK(mode):
                    raise ValueError('La copia contiene una ruta o enlace no permitido.')
                if not isinstance(metadata, dict) or metadata.get('size') != info.file_size:
                    raise ValueError('El tamaño no coincide con el manifiesto.')
                target = stage.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                digest = hashlib.sha256()
                with bundle.open(info) as source, target.open('xb') as output:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
                target.chmod(0o600)
                if digest.hexdigest() != metadata.get('sha256'):
                    raise ValueError('Falló la verificación SHA-256.')
        database = stage / 'cfb.sqlite3'
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
            if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('La base no superó la verificación de integridad.')
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, column in [('core_document', 'file'), ('core_company', 'logo')]:
                if table in tables:
                    for (value,) in connection.execute(f'SELECT {column} FROM {table}'):
                        if value and (not safe_name('private/' + value) or not (stage / 'private' / value).is_file()):
                            raise ValueError('Falta un documento referenciado por la base.')
        # mkdir is exclusive: a destination created concurrently is never overwritten.
        destination.mkdir(mode=0o700)
        try:
            for path in stage.iterdir():
                shutil.move(str(path), str(destination / path.name))
        except Exception:
            shutil.rmtree(destination)
            raise
    print(f'Copia verificada y restaurada en {destination}. Configure CFB_DATA_DIR y valide antes de abrir acceso.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, sqlite3.Error, zipfile.BadZipFile) as exc:
        raise SystemExit(f'No se restauró la copia: {exc}') from exc
