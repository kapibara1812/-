(function () {
  const listView = document.getElementById('list-view');
  const detailView = document.getElementById('detail-view');
  const cardsEl = document.getElementById('cards');
  const searchInput = document.getElementById('search-input');
  const filterBar = document.getElementById('filter-bar');
  const emptyState = document.getElementById('empty-state');
  const detailBody = document.getElementById('detail-body');
  const backBtn = document.getElementById('back-btn');
  const resultCount = document.getElementById('result-count');

  let activeCategory = 'all';

  function normalize(str) {
    return (str || '').toLowerCase();
  }

  function matchesQuery(item, query) {
    if (!query) return true;
    const haystack = normalize([item.title, item.summary, ...(item.tags || [])].join(' '));
    return haystack.includes(normalize(query));
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
      .map(
        (item) => `
      <button class="card" data-id="${item.id}">
        <span class="card-cat">${CATEGORY_LABELS[item.category] || item.category}</span>
        <h3 class="card-title">${item.title}</h3>
        <p class="card-summary">${item.summary}</p>
        <div class="card-tags">${(item.tags || []).slice(0, 4).map((t) => `<span>#${t}</span>`).join('')}</div>
      </button>`
      )
      .join('');
  }

  function renderDiagram(diagram) {
    let svg = '';
    if (diagram.type === 'candle') {
      svg = renderCandleSVG(diagram.data, diagram.opts);
    } else if (diagram.type === 'line') {
      svg = renderLineSVG(diagram.data, diagram.opts);
    }
    return `<figure class="diagram">
      ${svg}
      <figcaption>${diagram.caption}</figcaption>
    </figure>`;
  }

  function openDetail(id) {
    const item = KNOWLEDGE.find((k) => k.id === id);
    if (!item) return;

    detailBody.innerHTML = `
      <span class="card-cat">${CATEGORY_LABELS[item.category] || item.category}</span>
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
          <div>${s.html}</div>
        </section>`
        )
        .join('')}

      <section class="detail-section forecast">
        <h3>📈 今後のチャートの動き方</h3>
        <div>${item.forecast}</div>
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

  filterBar.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    activeCategory = chip.dataset.cat;
    renderFilterBar();
    renderCards();
  });

  searchInput.addEventListener('input', renderCards);
  backBtn.addEventListener('click', closeDetail);

  renderFilterBar();
  renderCards();

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('service-worker.js').catch(() => {});
    });
  }
})();
