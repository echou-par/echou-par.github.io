#!/usr/bin/env node
/**
 * build_teardown.js — Build a competitor teardown .docx from a JSON content file.
 *
 * Usage:
 *   node build_teardown.js <content.json> <output.docx>
 *
 * The JSON schema is documented in references/content_template.json.
 * A filled-in example is at references/spoton_example.json.
 *
 * Requires: npm install -g docx  (already installed in Claude.ai sandbox)
 */

const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, ExternalHyperlink, HeadingLevel,
  BorderStyle, WidthType, ShadingType,
} = require('docx');

// ---------- CLI ----------
if (process.argv.length < 4) {
  console.error('Usage: node build_teardown.js <content.json> <output.docx>');
  process.exit(1);
}
const inputPath = process.argv[2];
const outputPath = process.argv[3];

if (!fs.existsSync(inputPath)) {
  console.error(`Input file not found: ${inputPath}`);
  process.exit(1);
}
const content = JSON.parse(fs.readFileSync(inputPath, 'utf8'));

// ---------- PAR brand palette ----------
const PAR_PURPLE = '6864D1';
const PAR_DARK = '2F3452';
const TEXT_GREY = '555E7E';
const SOFT_GREY = '8A93AE';
const ACCENT_GREEN = '1F8A4C';
const ACCENT_RED = 'C03A2B';
const ACCENT_AMBER = 'B8861B';

// ---------- Border + shading helpers ----------
const border = { style: BorderStyle.SINGLE, size: 4, color: 'DDE0EC' };
const borders = { top: border, bottom: border, left: border, right: border };

// ---------- Run helpers ----------
const r = (text, opts = {}) => new TextRun({ text: String(text ?? ''), font: 'Arial', ...opts });
const rb = (text, opts = {}) => r(text, { bold: true, ...opts });
const rcap = (text, opts = {}) => r(text, { size: 16, color: SOFT_GREY, ...opts });

// ---------- Inline rich-text parser (super simple) ----------
// Supports **bold** in body strings. No nesting. Splits on the bold delimiter.
function parseInline(text, baseOpts = {}) {
  const parts = String(text ?? '').split(/(\*\*[^*]+\*\*)/g);
  return parts
    .filter(s => s.length > 0)
    .map(s => {
      if (s.startsWith('**') && s.endsWith('**')) {
        return rb(s.slice(2, -2), { size: 22, ...baseOpts });
      }
      return r(s, { size: 22, ...baseOpts });
    });
}

// Body paragraph from a string OR an array of strings (each becomes its own paragraph)
function body(textOrArray, opts = {}) {
  if (Array.isArray(textOrArray)) {
    return textOrArray.map(t => body(t, opts));
  }
  return new Paragraph({
    children: parseInline(textOrArray),
    spacing: { after: 140, line: 300 },
    ...opts,
  });
}

// Bullet list paragraphs from an array of strings
function bullets(items, level = 0) {
  return items.map(item => new Paragraph({
    children: parseInline(item),
    numbering: { reference: 'bullets', level },
    spacing: { after: 80, line: 280 },
  }));
}

// Headings
const h1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  children: [r(text)],
  spacing: { before: 360, after: 180 },
});
const h2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  children: [r(text)],
  spacing: { before: 240, after: 120 },
});
const h3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  children: [r(text)],
  spacing: { before: 180, after: 100 },
});

// ---------- Fact table (label / value pairs) ----------
function factTable(rows) {
  const buildRow = ([label, value]) => new TableRow({
    children: [
      new TableCell({
        borders,
        width: { size: 2400, type: WidthType.DXA },
        shading: { fill: 'F4F4FA', type: ShadingType.CLEAR },
        margins: { top: 100, bottom: 100, left: 140, right: 100 },
        children: [new Paragraph({ children: [rb(label, { size: 18, color: PAR_DARK })] })],
      }),
      new TableCell({
        borders,
        width: { size: 6960, type: WidthType.DXA },
        margins: { top: 100, bottom: 100, left: 140, right: 140 },
        children: [new Paragraph({ children: parseInline(value, { size: 20 }) })],
      }),
    ],
  });
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2400, 6960],
    rows: rows.map(buildRow),
  });
}

// ---------- SWOT cell ----------
function swotCell(title, items, fillColor, titleColor) {
  return new TableCell({
    borders,
    width: { size: 4680, type: WidthType.DXA },
    shading: { fill: fillColor, type: ShadingType.CLEAR },
    margins: { top: 140, bottom: 140, left: 160, right: 160 },
    children: [
      new Paragraph({
        children: [rb(title, { size: 22, color: titleColor })],
        spacing: { after: 100 },
      }),
      ...items.map(it => new Paragraph({
        children: [r('• ' + it, { size: 19 })],
        spacing: { after: 80, line: 260 },
      })),
    ],
  });
}

function swotTable(swot) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [4680, 4680],
    rows: [
      new TableRow({
        children: [
          swotCell('Strengths', swot.strengths || [], 'EAF6EE', ACCENT_GREEN),
          swotCell('Weaknesses', swot.weaknesses || [], 'FCEDEA', ACCENT_RED),
        ],
      }),
      new TableRow({
        children: [
          swotCell('Opportunities', swot.opportunities || [], 'F4F4FA', PAR_PURPLE),
          swotCell('Threats', swot.threats || [], 'FBF3DC', ACCENT_AMBER),
        ],
      }),
    ],
  });
}

// ---------- News table ----------
function newsRow(item) {
  const dateCell = new TableCell({
    borders,
    width: { size: 1500, type: WidthType.DXA },
    shading: { fill: 'FAFBFE', type: ShadingType.CLEAR },
    margins: { top: 100, bottom: 100, left: 120, right: 100 },
    children: [new Paragraph({ children: [rb(item.date, { size: 18, color: PAR_DARK })] })],
  });
  const newsCell = new TableCell({
    borders,
    width: { size: 4500, type: WidthType.DXA },
    margins: { top: 100, bottom: 100, left: 140, right: 140 },
    children: [
      new Paragraph({
        children: [rb(item.headline, { size: 20 })],
        spacing: { after: 60 },
      }),
      new Paragraph({
        children: [
          new ExternalHyperlink({
            link: item.url,
            children: [r(item.source, { size: 17, color: PAR_PURPLE, underline: {} })],
          }),
        ],
      }),
    ],
  });
  const takeawayCell = new TableCell({
    borders,
    width: { size: 3360, type: WidthType.DXA },
    margins: { top: 100, bottom: 100, left: 140, right: 140 },
    children: [
      new Paragraph({
        children: [
          rb('PAR Takeaway: ', { size: 18, color: ACCENT_AMBER }),
          r(item.takeaway, { size: 18 }),
        ],
        spacing: { line: 260 },
      }),
    ],
  });
  return new TableRow({ children: [dateCell, newsCell, takeawayCell] });
}

function newsTable(items) {
  const headerRow = new TableRow({
    tableHeader: true,
    children: [
      ['Date', 1500],
      ['Headline & Source', 4500],
      ['Takeaway / Implication', 3360],
    ].map(([label, w]) => new TableCell({
      borders,
      width: { size: w, type: WidthType.DXA },
      shading: { fill: PAR_PURPLE, type: ShadingType.CLEAR },
      margins: { top: 100, bottom: 100, left: 140, right: 140 },
      children: [new Paragraph({ children: [rb(label, { size: 18, color: 'FFFFFF' })] })],
    })),
  });
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [1500, 4500, 3360],
    rows: [headerRow, ...items.map(newsRow)],
  });
}

// ---------- Build sections ----------
const children = [];

// Title page
children.push(
  new Paragraph({
    children: [rb((content.competitor_name || '').toUpperCase(), { size: 56, color: PAR_PURPLE })],
    spacing: { before: 600, after: 80 },
  }),
  new Paragraph({
    children: [rb('Competitor Teardown & Strategic Overview', { size: 36, color: PAR_DARK })],
    spacing: { after: 120 },
  }),
  new Paragraph({
    children: [r('Companion deep-dive to the PAR Competitive Intelligence Monitor', { size: 22, color: TEXT_GREY, italics: true })],
    spacing: { after: 60 },
  }),
  new Paragraph({
    children: [rcap(`Prepared ${content.prepared_date || ''} · Updated continuously via dashboard`)],
    spacing: { after: 240 },
  }),
);

// 1. Executive Summary
if (content.executive_summary) {
  children.push(h1('1. Executive Summary'));
  const paras = Array.isArray(content.executive_summary) ? content.executive_summary : [content.executive_summary];
  paras.forEach(p => children.push(body(p)));
}

// 2. Company Snapshot
if (content.company_snapshot) {
  children.push(h1('2. Company Snapshot'));
  const rows = Object.entries(content.company_snapshot);
  children.push(factTable(rows));
}

// 3. Strategy & Positioning
if (content.strategy) {
  children.push(h1('3. Strategy & Positioning'));
  const s = content.strategy;
  if (s.thesis) {
    children.push(h2('3.1 Strategic Thesis'));
    (Array.isArray(s.thesis) ? s.thesis : [s.thesis]).forEach(p => children.push(body(p)));
  }
  if (Array.isArray(s.pillars) && s.pillars.length > 0) {
    children.push(h2('3.2 Strategic Pillars'));
    s.pillars.forEach((pillar, i) => {
      children.push(h3(`Pillar ${i + 1}: ${pillar.title}`));
      (Array.isArray(pillar.body) ? pillar.body : [pillar.body]).forEach(p => children.push(body(p)));
    });
  }
  if (Array.isArray(s.inflection_points) && s.inflection_points.length > 0) {
    children.push(h2('3.3 Strategic Inflection Points'));
    children.push(...bullets(s.inflection_points));
  }
}

// 4. ICP
if (content.icp) {
  children.push(h1('4. Ideal Customer Profile (ICP)'));
  if (content.icp.intro) {
    (Array.isArray(content.icp.intro) ? content.icp.intro : [content.icp.intro]).forEach(p => children.push(body(p)));
  }
  if (Array.isArray(content.icp.segments)) {
    content.icp.segments.forEach(seg => {
      children.push(h2(seg.title));
      if (seg.attributes && typeof seg.attributes === 'object') {
        children.push(factTable(Object.entries(seg.attributes)));
      }
      if (seg.note) children.push(body(seg.note));
    });
  }
  if (Array.isArray(content.icp.anti_icp) && content.icp.anti_icp.length > 0) {
    children.push(h2('Anti-ICP — Segments Explicitly Not Targeted'));
    children.push(...bullets(content.icp.anti_icp));
  }
}

// 5. Product & Service Differentiation
if (content.product_diff) {
  children.push(h1('5. Product & Service Differentiation'));
  const pd = content.product_diff;
  if (pd.overview) {
    children.push(h2('5.1 Product Suite Overview'));
    (Array.isArray(pd.overview) ? pd.overview : [pd.overview]).forEach(p => children.push(body(p)));
  }
  if (Array.isArray(pd.products) && pd.products.length > 0) {
    children.push(...bullets(pd.products));
  }
  if (Array.isArray(pd.strengths) && pd.strengths.length > 0) {
    children.push(h2('5.2 What They Do Better Than Most'));
    children.push(...bullets(pd.strengths));
  }
  if (Array.isArray(pd.weaknesses) && pd.weaknesses.length > 0) {
    children.push(h2('5.3 Where They Are Weak (Opportunity for PAR)'));
    children.push(...bullets(pd.weaknesses));
  }
  if (pd.pricing) {
    children.push(h2('5.4 Pricing Posture'));
    (Array.isArray(pd.pricing) ? pd.pricing : [pd.pricing]).forEach(p => children.push(body(p)));
  }
}

// 6. SWOT
if (content.swot) {
  children.push(h1('6. SWOT Analysis'));
  if (content.swot.intro) {
    children.push(new Paragraph({
      children: [r(content.swot.intro, { size: 22, italics: true, color: TEXT_GREY })],
      spacing: { after: 140, line: 300 },
    }));
  }
  children.push(swotTable(content.swot));
}

// 7. News & Implications
if (Array.isArray(content.news) && content.news.length > 0) {
  children.push(h1('7. Key News & Strategic Implications'));
  if (content.news_intro) {
    (Array.isArray(content.news_intro) ? content.news_intro : [content.news_intro]).forEach(p => children.push(body(p)));
  }
  children.push(newsTable(content.news));
}

// 8. PAR Playbook
if (content.par_playbook) {
  children.push(h1('8. PAR Competitive Playbook'));
  const pp = content.par_playbook;
  if (Array.isArray(pp.engage) && pp.engage.length > 0) {
    children.push(h2('8.1 Where to Engage Aggressively'));
    children.push(...bullets(pp.engage));
  }
  if (Array.isArray(pp.avoid) && pp.avoid.length > 0) {
    children.push(h2('8.2 Where to Avoid Direct Confrontation'));
    children.push(...bullets(pp.avoid));
  }
  if (Array.isArray(pp.signals) && pp.signals.length > 0) {
    children.push(h2('8.3 Signals to Watch in the Dashboard'));
    children.push(...bullets(pp.signals));
  }
  if (Array.isArray(pp.actions) && pp.actions.length > 0) {
    children.push(h2('8.4 Concrete Actions'));
    children.push(...bullets(pp.actions));
  }
}

// Footer
children.push(
  new Paragraph({ spacing: { before: 480, after: 100 }, children: [r('—', { size: 22, color: SOFT_GREY })] }),
  new Paragraph({
    spacing: { after: 140, line: 300 },
    children: [
      rcap('This teardown is a companion to the PAR Competitive Intelligence Monitor. Real-time data — news, product updates, financial signals, and AI-summarized strategic moves — is maintained at '),
      new ExternalHyperlink({
        link: 'https://echou-par.github.io/par-comp-intel/',
        children: [rcap('echou-par.github.io/par-comp-intel', { color: PAR_PURPLE, underline: {} })],
      }),
      rcap('.'),
    ],
  }),
);

// ---------- Build document ----------
const doc = new Document({
  creator: 'PAR Competitive Intelligence',
  title: `${content.competitor_name} — Competitor Teardown`,
  description: `Strategic deep-dive on ${content.competitor_name} for the PAR Competitive Intelligence Monitor`,
  styles: {
    default: { document: { run: { font: 'Arial', size: 22 } } },
    paragraphStyles: [
      {
        id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 32, bold: true, font: 'Arial', color: PAR_PURPLE },
        paragraph: { spacing: { before: 400, after: 200 }, outlineLevel: 0 },
      },
      {
        id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 26, bold: true, font: 'Arial', color: PAR_DARK },
        paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1 },
      },
      {
        id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 22, bold: true, font: 'Arial', color: PAR_PURPLE },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: 'bullets',
        levels: [
          {
            level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 540, hanging: 280 } } },
          },
          {
            level: 1, format: LevelFormat.BULLET, text: '◦', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1080, hanging: 280 } } },
          },
        ],
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 }, // US Letter
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, buf);
  console.log(`Wrote ${outputPath} (${buf.length} bytes, ${children.length} top-level blocks)`);
});
