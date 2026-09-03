"""Loopback-only semantic search service; holds one OpenCLIP model in memory."""

from __future__ import annotations

import numpy as np
from flask import Flask, jsonify, request

from catalog import connect_db, init_db
from semantic_model import MODEL_ID, embed_text, load_model


app = Flask(__name__)
init_db()


@app.get('/healthz')
def health():
    with connect_db() as db:
        ready = db.execute(
            "SELECT COUNT(*) FROM media_items WHERE embedding_status = 'ready' "
            'AND embedding_model = ?', (MODEL_ID,)
        ).fetchone()[0]
    return jsonify({'status': 'ok', 'model': MODEL_ID, 'ready': ready})


@app.get('/search')
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'Enter a visual search description.'}), 400
    where = ["m.embedding_status = 'ready'", 'm.embedding_model = ?']
    params: list[object] = [MODEL_ID]
    collection = request.args.get('collection')
    if collection:
        where.append('m.collection = ?'); params.append(collection)
    year = request.args.get('year', type=int)
    if year:
        where.append('m.captured_year = ?'); params.append(year)
    media_type = request.args.get('type')
    if media_type in ('image', 'video'):
        where.append('m.media_type = ?'); params.append(media_type)
    camera = request.args.get('camera')
    if camera:
        where.append('m.camera = ?'); params.append(camera)
    joins = ''
    user_id = request.args.get('user_id', type=int)
    if request.args.get('favorites') == '1' and user_id:
        joins = ' JOIN user_favorites uf ON uf.media_id = m.id AND uf.user_id = ?'
        params.insert(0, user_id)
    with connect_db() as db:
        rows = db.execute(
            f'''SELECT m.id, m.collection, m.subpath, m.name, m.media_type,
                       m.captured_at, m.captured_year, m.camera, m.width, m.height,
                       m.embedding
                FROM media_items m{joins} WHERE {' AND '.join(where)}''', params
        ).fetchall()
    if not rows:
        return jsonify({'results': [], 'count': 0, 'total_pages': 1, 'indexed': 0})
    matrix = np.stack([np.frombuffer(row['embedding'], dtype=np.float32) for row in rows])
    scores = matrix @ embed_text(query)
    order = np.argsort(-scores)
    page = max(1, request.args.get('page', 1, type=int))
    limit = min(200, max(24, request.args.get('limit', 120, type=int)))
    selection = order[(page - 1) * limit:page * limit]
    results = []
    for index in selection:
        item = dict(rows[int(index)])
        item.pop('embedding')
        item['score'] = round(float(scores[int(index)]), 4)
        results.append(item)
    return jsonify({
        'results': results, 'count': len(rows), 'indexed': len(rows), 'page': page,
        'total_pages': max(1, (len(rows) + limit - 1) // limit),
    })


if __name__ == '__main__':
    load_model()
    app.run(host='127.0.0.1', port=5051)
