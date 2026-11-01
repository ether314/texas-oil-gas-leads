// Small pure text helpers: nothing here touches the page, so the tests can import them under Node (util.js re-exports them for the views).

// "1 permits" is a slip: a unit phrase in its plural form ("new-drill permits issued", "wells spudded") turned singular when the count is one
export const unitOf = (n, text) => (n === 1 ? text.replace(/\b(permits|applications|completions|filings|wells|spuds)\b/, (w) => w.slice(0, -1)) : text);

// a fraction as a whole percent that never reads 100% unless it is (99.5% of permits located is "99%"): the Overview and the Map print the same share the same way
export const sharePct = (x) => (x >= 1 ? '100%' : Math.min(99, Math.round(x * 100)) + '%');
