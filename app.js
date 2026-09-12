(function () {
  const listView = document.getElementById('list-view');
  const detailView = document.getElementById('detail-view');
  const cardsEl = document.getElementById('cards');
  const searchInput = document.getElementById('search-input');
  const filterBar = document.getElementById('filter-bar');
  const emptyState = document.getElementById('empty-state');
  const detailBody = document.getElementById('detail-body');
  const backBtns = document.querySelectorAll('.back-btn');
  const resultCount = document.getElementById('result-count');

  let activeCategory = 'all';

  function normalize(str) {
    return (str || '').toLowerCase();
  }

  function renderDiagramSVG(diagram, sizeOpts) {
    const opts = Object.assign({}, diagram.opts, sizeOpts);
    if (diagram.type === 'candle') return renderCandleSVG(diagram.data, opts);
    if (diagram.type === 'price-volume') return renderPriceVolumeSVG(diagram.data.points, diagram.data.volumes, opts);
    return renderLineSVG(diagram.data, opts);
  }

  function matchesQuery(item, query) {
    if (!query) return true;
    const haystack = normalize([item.title, item.summary, ...(item.tags || [])].join(' '));
    return haystack.includes(normalize(query));
  }

  function selectCategory(cat) {
    activeCategory = cat;
    renderFilterBar();
    renderCards();
  }

  function renderFilterBar() {
    const categories = ['all', ...new Set(KNOWLEDGE.map((k) => k.category))];
    filterBar.innerHTML = categories
      .map((cat) => {
        const label = cat === 'all' ? 'すべて' : CATEGORY_LABELS[cat] || cat;
        const active = cat === activeCategory ? 'is-active' : '';
        return `<button class="chip ${active}" data-cat="${cat}">${label}</button>`;
      })
      .join('');
  }

  function renderCards() {
    const query = searchInput.value.trim();
    const filtered = KNOWLEDGE.filter(
      (item) => (activeCategory === 'all' || item.category === activeCategory) && matchesQuery(item, query)
    );

    resultCount.textContent = `${filtered.length}件`;
    emptyState.hidden = filtered.length !== 0;

    cardsEl.innerHTML = filtered
      .map((item) => {
        const thumb = item.diagrams && item.diagrams[0];
        const thumbSvg = thumb ? renderDiagramSVG(thumb, { width: 80, height: 80 }) : '';
        const accent = CATEGORY_COLORS[item.category] || '#8b5cf6';
        return `
      <button class="card" data-id="${item.id}" style="--card-accent:${accent}">
        ${thumbSvg ? `<div class="card-thumb">${thumbSvg}</div>` : ''}
        <div class="card-main">
          <span class="card-cat" data-cat="${item.category}">${CATEGORY_LABELS[item.category] || item.category}</span>
          <h3 class="card-title">${item.title}</h3>
          <p class="card-summary">${item.summary}</p>
          <div class="card-tags">${(item.tags || []).slice(0, 4).map((t) => `<span>#${t}</span>`).join('')}</div>
        </div>
      </button>`;
      })
      .join('');
  }

  function resolveInlineLinks(html) {
    return html.replace(/\[\[([\w-]+)\]\]/g, (match, id) => {
      const target = KNOWLEDGE.find((k) => k.id === id);
      if (!target) return match;
      return `<a href="#" class="inline-link" data-nav-id="${id}">${target.title}</a>`;
    });
  }

  function renderDiagram(diagram) {
    return `<figure class="diagram">
      ${renderDiagramSVG(diagram)}
      <figcaption>${diagram.caption}</figcaption>
    </figure>`;
  }

  function openDetail(id) {
    const item = KNOWLEDGE.find((k) => k.id === id);
    if (!item) return;

    detailBody.innerHTML = `
      <button class="card-cat card-cat-link" data-cat="${item.category}">${CATEGORY_LABELS[item.category] || item.category}</button>
      <h2 class="detail-title">${item.title}</h2>
      <p class="detail-summary">${item.summary}</p>

      <div class="diagram-grid">
        ${(item.diagrams || []).map(renderDiagram).join('')}
      </div>

      ${item.sections
        .map(
          (s) => `
        <section class="detail-section">
          <h3>${s.heading}</h3>
          <div>${resolveInlineLinks(s.html)}</div>
        </section>`
        )
        .join('')}

      <section class="detail-section forecast">
        <h3>今後のチャートの動き方</h3>
        <div>${resolveInlineLinks(item.forecast)}</div>
      </section>

      <div class="card-tags detail-tags">${(item.tags || []).map((t) => `<span>#${t}</span>`).join('')}</div>
    `;

    listView.hidden = true;
    detailView.hidden = false;
    detailView.scrollTop = 0;
    window.scrollTo(0, 0);
  }

  function closeDetail() {
    detailView.hidden = true;
    listView.hidden = false;
  }

  cardsEl.addEventListener('click', (e) => {
    const card = e.target.closest('.card');
    if (card) openDetail(card.dataset.id);
  });

  detailBody.addEventListener('click', (e) => {
    const catBtn = e.target.closest('.card-cat-link');
    if (catBtn) {
      selectCategory(catBtn.dataset.cat);
      closeDetail();
      return;
    }
    const link = e.target.closest('.inline-link');
    if (!link) return;
    e.preventDefault();
    openDetail(link.dataset.navId);
  });

  filterBar.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    selectCategory(chip.dataset.cat);
  });

  searchInput.addEventListener('input', renderCards);
  backBtns.forEach((btn) => btn.addEventListener('click', closeDetail));

  renderFilterBar();
  renderCards();

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('service-worker.js').catch(() => {});
    });
  }
})();
