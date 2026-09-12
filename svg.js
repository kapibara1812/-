// SVG図解を動的に生成するユーティリティ群
// candles: [{o,h,l,c}] (値は0-100の相対スケール)
function renderCandleSVG(candles, opts = {}) {
  const width = opts.width || 320;
  const height = opts.height || 240;
  const padTop = 20, padBottom = 20, padSide = 20;
  const innerH = height - padTop - padBottom;
  const step = (width - padSide * 2) / candles.length;
  const bodyW = Math.max(8, Math.min(step * 0.55, 46));
  const scaleY = (v) => padTop + innerH - (v / 100) * innerH;

  let bars = '';
  candles.forEach((c, i) => {
    const cx = padSide + step * i + step / 2;
    const up = c.c >= c.o;
    const color = up ? '#d9424c' : '#2b6cb0';
    const yHigh = scaleY(c.h);
    const yLow = scaleY(c.l);
    const yOpen = scaleY(c.o);
    const yClose = scaleY(c.c);
    const bodyTop = Math.min(yOpen, yClose);
    const bodyH = Math.max(2, Math.abs(yClose - yOpen));
    bars += `<line x1="${cx}" y1="${yHigh}" x2="${cx}" y2="${yLow}" stroke="${color}" stroke-width="2"/>`;
    bars += `<rect x="${cx - bodyW / 2}" y="${bodyTop}" width="${bodyW}" height="${bodyH}" fill="${up ? color : color}" stroke="${color}" />`;
    if (c.label) {
      bars += `<text x="${cx}" y="${height - 2}" font-size="9" text-anchor="middle" fill="var(--muted)">${c.label}</text>`;
    }
  });

  return `<svg viewBox="0 0 ${width} ${height}" class="diagram-svg" role="img" aria-label="ローソク足図解">
    <rect x="0" y="0" width="${width}" height="${height}" fill="var(--diagram-bg)" rx="8"/>
    ${bars}
  </svg>`;
}

// points: [{x,y,label?,labelPos?}] x,yは0-100スケール(yは上が大きい値=価格が高い、として上向きに変換)
// labelPosを省略すると前後の点との比較から山(top)/谷(bottom)を自動判定する
function renderLineSVG(points, opts = {}) {
  const width = opts.width || 320;
  const height = opts.height || 200;
  const padTop = 26, padBottom = 26, padSide = 18;
  const innerW = width - padSide * 2;
  const innerH = height - padTop - padBottom;
  const scaleX = (x) => padSide + (x / 100) * innerW;
  const scaleY = (y) => padTop + innerH - (y / 100) * innerH;

  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.x)} ${scaleY(p.y)}`).join(' ');
  let dots = '';
  let labels = '';
  points.forEach((p, i) => {
    dots += `<circle cx="${scaleX(p.x)}" cy="${scaleY(p.y)}" r="4" fill="${opts.dotColor || '#d9424c'}"/>`;
    if (p.label) {
      let pos = p.labelPos;
      if (!pos) {
        const prev = points[i - 1];
        const next = points[i + 1];
        if (prev && next) pos = (p.y >= prev.y && p.y >= next.y) ? 'top' : (p.y <= prev.y && p.y <= next.y) ? 'bottom' : 'top';
        else if (prev) pos = p.y >= prev.y ? 'top' : 'bottom';
        else pos = 'top';
      }
      const ly = pos === 'bottom' ? scaleY(p.y) + 17 : scaleY(p.y) - 11;
      labels += `<text x="${scaleX(p.x)}" y="${ly}" font-size="12" font-weight="700" text-anchor="middle" fill="var(--text)" stroke="var(--diagram-bg)" stroke-width="4" paint-order="stroke">${p.label}</text>`;
    }
  });

  let extraLines = '';
  (opts.extraLines || []).forEach((line) => {
    const d = line.points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.x)} ${scaleY(p.y)}`).join(' ');
    extraLines += `<path d="${d}" fill="none" stroke="${line.color || 'var(--muted)'}" stroke-width="${line.width || 1.5}" stroke-dasharray="${line.dash || '0'}"/>`;
  });

  return `<svg viewBox="0 0 ${width} ${height}" class="diagram-svg" role="img" aria-label="トレンド図解">
    <rect x="0" y="0" width="${width}" height="${height}" fill="var(--diagram-bg)" rx="8"/>
    ${extraLines}
    <path d="${pathD}" fill="none" stroke="${opts.lineColor || '#2b6cb0'}" stroke-width="2.5"/>
    ${dots}
    ${labels}
  </svg>`;
}

// 価格ライン(points)と出来高の棒グラフ(volumes)を上下に重ねて表示する図解
// points: [{x,y,label?,labelPos?}] volumes: [{x,v,color?}]
function renderPriceVolumeSVG(points, volumes, opts = {}) {
  const width = opts.width || 320;
  const height = opts.height || 220;
  const padSide = 18;
  const innerW = width - padSide * 2;
  const scaleX = (x) => padSide + (x / 100) * innerW;

  const priceTop = 16, priceBottom = Math.round(height * 0.6);
  const priceInnerH = priceBottom - priceTop;
  const scaleYPrice = (y) => priceTop + priceInnerH - (y / 100) * priceInnerH;
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.x)} ${scaleYPrice(p.y)}`).join(' ');
  let labels = '';
  points.forEach((p) => {
    if (!p.label) return;
    const pos = p.labelPos || 'top';
    const ly = pos === 'bottom' ? scaleYPrice(p.y) + 15 : scaleYPrice(p.y) - 9;
    labels += `<text x="${scaleX(p.x)}" y="${ly}" font-size="11" font-weight="700" text-anchor="middle" fill="var(--text)" stroke="var(--diagram-bg)" stroke-width="3" paint-order="stroke">${p.label}</text>`;
  });

  const volTop = priceBottom + 14;
  const volBottom = height - 8;
  const volInnerH = volBottom - volTop;
  const maxV = Math.max(...volumes.map((v) => v.v), 1);
  const step = innerW / volumes.length;
  const barW = Math.max(4, step * 0.55);
  let bars = '';
  volumes.forEach((v, i) => {
    const h = (v.v / maxV) * volInnerH;
    const x = padSide + step * i + (step - barW) / 2;
    const y = volBottom - h;
    bars += `<rect x="${x}" y="${y}" width="${barW}" height="${h}" fill="${v.color || opts.lineColor || '#8b5cf6'}" rx="2"/>`;
  });

  return `<svg viewBox="0 0 ${width} ${height}" class="diagram-svg" role="img" aria-label="価格と出来高の図解">
    <rect x="0" y="0" width="${width}" height="${height}" fill="var(--diagram-bg)" rx="8"/>
    <path d="${pathD}" fill="none" stroke="${opts.lineColor || '#d9424c'}" stroke-width="2.5"/>
    ${labels}
    <line x1="${padSide}" y1="${priceBottom + 6}" x2="${width - padSide}" y2="${priceBottom + 6}" stroke="var(--border)" stroke-width="1"/>
    ${bars}
  </svg>`;
}
