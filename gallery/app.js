(function () {
  'use strict';
  const grid = document.getElementById('gallery'), box = document.getElementById('lightbox');
  let items = [], shown = [], current = 0;
  function text(tag, value, cls) { const node = document.createElement(tag); node.textContent = value; if (cls) node.className = cls; return node; }
  function show(index) {
    current = (index + shown.length) % shown.length;
    const item = shown[current], picture = document.getElementById('picture');
    picture.src = item.file; picture.alt = item.title + ': ' + item.caption;
    document.getElementById('picture-title').textContent = item.title;
    document.getElementById('picture-caption').textContent = item.caption;
    if (!box.open) box.showModal();
  }
  function render(filter) {
    shown = items.filter(item => filter === 'all' || item.group === filter);
    grid.replaceChildren();
    shown.forEach((item, index) => {
      const card = document.createElement('figure'), button = document.createElement('button'), image = document.createElement('img');
      card.className = 'card';
      button.type = 'button'; button.setAttribute('aria-label', 'Show ' + item.title + ' full size');
      image.src = item.file; image.alt = ''; image.loading = 'lazy'; image.width = 640; image.height = 360;
      button.append(image); button.addEventListener('click', () => show(index));
      const caption = document.createElement('figcaption');
      caption.append(text('h3', item.title), text('p', item.caption), text('p', item.kind, 'kind'));
      card.append(button, caption); grid.append(card);
    });
  }
  document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-filter]').forEach(other => other.setAttribute('aria-pressed', String(other === button)));
    render(button.dataset.filter);
  }));
  document.getElementById('close').addEventListener('click', () => box.close());
  document.getElementById('previous').addEventListener('click', () => show(current - 1));
  document.getElementById('next').addEventListener('click', () => show(current + 1));
  box.addEventListener('click', event => { if (event.target === box) box.close(); });
  document.addEventListener('keydown', event => {
    if (!box.open) return;
    if (event.key === 'ArrowLeft') show(current - 1);
    if (event.key === 'ArrowRight') show(current + 1);
  });
  fetch('manifest.json')
    .then(response => { if (!response.ok) throw new Error(); return response.json(); })
    .then(manifest => {
      items = manifest.items;
      document.getElementById('version').textContent = manifest.version || '';
      render('all');
    })
    .catch(() => grid.replaceChildren(text('p', 'The screenshots couldn’t be loaded. Open this page from the Windows customiser.', 'hint')));
})();
