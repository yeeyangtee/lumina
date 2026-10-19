"""Generate local OpenCLIP embeddings for catalogue media."""

from __future__ import annotations

from job_lock import single_job

import argparse
import io

from PIL import Image

from app import BASE_DIRS, get_or_create_thumb
from catalog import connect_db, init_db, update_job
from media_cache import poster_cache_file
from semantic_model import MODEL_ID, embed_images


def _open_preview(row: dict) -> Image.Image:
    source = BASE_DIRS[row['collection']] / row['subpath']
    st = source.stat()
    if (st.st_size, st.st_mtime_ns) != (row['size'], row['mtime_ns']):
        raise OSError('Source changed')
    if row['media_type'] == 'video':
        with Image.open(poster_cache_file(source)) as preview:
            image = preview.convert('RGB')
    else:
        data = get_or_create_thumb(source)
        if not data:
            raise OSError('thumbnail generation failed')
        with Image.open(io.BytesIO(data)) as preview:
            image = preview.convert('RGB')
    st = source.stat()
    if (st.st_size, st.st_mtime_ns) != (row['size'], row['mtime_ns']):
        image.close()
        raise OSError('Source changed during preview read')
    return image


@single_job('semantic')
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--retry-errors', action='store_true')
    args = parser.parse_args()
    init_db()
    statuses = "('pending', 'error')" if args.retry_errors else "('pending')"
    with connect_db() as db:
        db.execute(
            "UPDATE media_items SET embedding_status = 'pending', embedding = NULL "
            'WHERE embedding_model IS NOT NULL AND embedding_model != ?',
            (MODEL_ID,),
        )
        total = db.execute(
            f"""SELECT COUNT(*) FROM media_items
                WHERE embedding_status IN {statuses} AND preview_status='ready'
                  AND (media_type = 'image' OR poster_status = 'ready')"""
        ).fetchone()[0]
        sql = (
            'SELECT id, collection, subpath, media_type,size,mtime_ns FROM media_items '
            f"WHERE embedding_status IN {statuses} AND preview_status='ready' "
            "AND (media_type = 'image' OR poster_status = 'ready') ORDER BY id"
        )
        if args.limit > 0:
            sql += f' LIMIT {int(args.limit)}'
        rows = [dict(row) for row in db.execute(sql)]

    update_job('semantic', 'running', 0, total)
    processed = errors = 0
    batch_size = max(1, min(args.batch_size, 32))
    for start in range(0, len(rows), batch_size):
        batch_rows = rows[start : start + batch_size]
        good_rows, images = [], []
        for row in batch_rows:
            try:
                images.append(_open_preview(row))
                good_rows.append(row)
            except Exception as exc:
                errors += 1
                with connect_db() as db:
                    db.execute(
                        "UPDATE media_items SET embedding_status = 'error' WHERE id = ? AND size=? AND mtime_ns=?",
                        (row['id'], row['size'], row['mtime_ns']),
                    )
                print(
                    f'embedding preview failed: {row["collection"]}/{row["subpath"]}: {exc}'
                )
        if images:
            vectors = embed_images(images)
            with connect_db() as db:
                db.executemany(
                    """UPDATE media_items SET embedding = ?, embedding_model = ?,
                           embedding_status = 'ready' WHERE id = ? AND size=? AND mtime_ns=?""",
                    [
                        (
                            vector.tobytes(),
                            MODEL_ID,
                            row['id'],
                            row['size'],
                            row['mtime_ns'],
                        )
                        for row, vector in zip(good_rows, vectors)
                    ],
                )
        for image in images:
            image.close()
        processed += len(batch_rows)
        update_job('semantic', 'running', processed, total)
        print(f'semantic: {processed}/{len(rows)}', flush=True)
    update_job(
        'semantic', 'ready', processed, total, f'{errors} failed' if errors else None
    )
    print(f'semantic: processed {processed}, errors {errors}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
