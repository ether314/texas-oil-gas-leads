// Date helpers for the Daily report. No DOM and no imports, so the merge code in daily-data.js can run under Node as well.
// Every day is an ISO string read at UTC noon, so a day never slips across a clock change.
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const WDL = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MOL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export const at = (iso) => new Date(iso + 'T12:00:00Z');
export const weekday = (iso) => at(iso).getUTCDay();
export const isWeekend = (iso) => { const d = weekday(iso); return d === 0 || d === 6; };
export const fmtMd = (iso) => MO[+iso.slice(5, 7) - 1] + ' ' + +iso.slice(8);
export const fmtDow = (iso) => WD[weekday(iso)] + ', ' + fmtMd(iso);
export const fmtLong = (iso) => WDL[weekday(iso)] + ', ' + MOL[+iso.slice(5, 7) - 1] + ' ' + +iso.slice(8) + ', ' + iso.slice(0, 4);
export const monthName = (iso) => MOL[+iso.slice(5, 7) - 1];
export const addDays = (iso, n) => new Date(at(iso).getTime() + n * 864e5).toISOString().slice(0, 10);
