const VIDEO_EXTS = ['.mp4', '.mov', '.m4v', '.webm'];

function isVideo(name) {
  return VIDEO_EXTS.some(ext => name.toLowerCase().endsWith(ext));
}

function encodeMediaPath(path) {
  return String(path).split('/').map(encodeURIComponent).join('/');
}

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

function escapeHtml(value) {
  const node = document.createElement('div');
  node.textContent = String(value);
  return node.innerHTML;
}

async function apiFetch(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  options.headers = new Headers(options.headers || {});
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    options.headers.set('X-CSRF-Token', csrfToken());
  }
  const response = await fetch(url, options);
  if (response.status === 401) {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
    throw new Error('Authentication required');
  }
  return response;
}

function lazyLoadThumbs(root = document) {
  const images = root.querySelectorAll('img.lazy-thumb:not([data-observed])');
  if (!('IntersectionObserver' in window)) {
    images.forEach(img => { img.src = img.dataset.src; if (img.dataset.srcset) img.srcset = img.dataset.srcset; });
    return null;
  }
  const observer = new IntersectionObserver((entries, obs) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.src = entry.target.dataset.src;
      if (entry.target.dataset.srcset) entry.target.srcset = entry.target.dataset.srcset;
      obs.unobserve(entry.target);
    });
  }, { rootMargin: '500px' });
  images.forEach(img => { img.dataset.observed = '1'; observer.observe(img); });
  return observer;
}

function makeThumbCard(opts) {
  const card = document.createElement('article');
  card.className = 'media-card';
  const link = document.createElement('a');
  link.href = opts.href;
  link.className = 'thumb-card';
  if (opts.title) link.title = opts.title;

  const img = document.createElement('img');
  img.className = 'lazy-thumb';
  img.dataset.src = opts.thumbSrc;
  if (!opts.video && opts.responsive !== false) {
    const join = opts.thumbSrc.includes('?') ? '&' : '?';
    img.dataset.srcset = `${opts.thumbSrc}${join}size=240 240w, ${opts.thumbSrc}${join}size=400 400w, ${opts.thumbSrc}${join}size=800 800w`;
    img.sizes = '(max-width: 430px) 50vw, (max-width: 700px) 33vw, 200px';
  }
  img.alt = opts.title || '';
  img.loading = 'lazy';
  img.decoding = 'async';
  img.onerror = () => {
    if (!opts.video) return;
    const placeholder = document.createElement('div');
    placeholder.className = 'folder-placeholder';
    placeholder.textContent = '▶';
    img.replaceWith(placeholder);
  };
  link.appendChild(img);

  if (opts.video) {
    link.classList.add('video-card');
    const badge = document.createElement('div');
    badge.className = 'play-badge';
    badge.textContent = '▶';
    link.appendChild(badge);
  }
  if (opts.label) {
    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = opts.label;
    link.appendChild(label);
  }
  card.appendChild(link);

  if (opts.favoriteAction) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'card-favorite' + (opts.fav ? ' active' : '');
    button.setAttribute('aria-label', opts.fav ? 'Remove favorite' : 'Add favorite');
    button.textContent = opts.fav ? '♥' : '♡';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const response = await apiFetch(opts.favoriteAction, { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not update favorite');
        button.classList.toggle('active', data.favorited);
        button.textContent = data.favorited ? '♥' : '♡';
        button.setAttribute('aria-label', data.favorited ? 'Remove favorite' : 'Add favorite');
        if (opts.onFavoriteChange) opts.onFavoriteChange(data.favorited, card);
      } catch (error) {
        showToast(error.message, 'error');
      } finally { button.disabled = false; }
    });
    card.appendChild(button);
  } else if (opts.fav) {
    const heart = document.createElement('div');
    heart.className = 'fav-badge';
    heart.textContent = '♥';
    card.appendChild(heart);
  }
  return card;
}

function mediaCardOptions(item, extra = {}) {
  const path = encodeMediaPath(item.subpath);
  const collection = encodeURIComponent(item.collection);
  const video = item.media_type ? item.media_type === 'video' : isVideo(item.subpath);
  return {
    href: `/view/${collection}/${path}`,
    title: item.name || item.subpath,
    thumbSrc: video ? `/poster/${collection}/${path}` : `/thumb/${collection}/${path}`,
    video,
    fav: Boolean(item.favorite),
    favoriteAction: `/api/favorite/${collection}/${path}`,
    ...extra,
  };
}

function wireSearchForm(collection = '') {
  const form = document.getElementById('search-form');
  if (!form) return;
  form.addEventListener('submit', event => {
    event.preventDefault();
    const query = document.getElementById('search-input').value.trim();
    const root = collection ? `/search/${encodeURIComponent(collection)}` : '/search';
    location.href = root + (query ? '?q=' + encodeURIComponent(query) : '');
  });
}

function showToast(message, type = 'success') {
  let stack = document.querySelector('.toast-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.className = 'toast-stack';
    document.body.appendChild(stack);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  stack.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('visible'));
  setTimeout(() => { toast.classList.remove('visible'); setTimeout(() => toast.remove(), 250); }, 2600);
}

function rememberScroll() {
  document.addEventListener('click', event => {
    if (event.target.closest('.thumb-card, .folder-card')) {
      sessionStorage.setItem('scroll:' + location.pathname + location.search, String(scrollY));
    }
  });
  const saved = sessionStorage.getItem('scroll:' + location.pathname + location.search);
  if (saved) requestAnimationFrame(() => scrollTo(0, Number(saved)));
}

document.addEventListener('DOMContentLoaded', rememberScroll);
