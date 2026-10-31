// What New Mexico's Daily report says about its one dataset. The Oil Conservation Division publishes no daily file: the report is read
// from its well layer (wells in status New, by the day their permit to drill was approved). daily.js puts it into the combined report.
export const NM_TITLES = { permits: 'Permits to drill', wells: 'Well inventory' };
export const NM_ICONS = { permits: 'pin', wells: 'rig' };
export const NM_WHAT = {
  permits: 'Wells in status New in the Oil Conservation Division\'s well layer, by the day their permit to drill was approved. The layer is entered some days after an approval, so the newest days fill in later.',
  wells: 'Every well in the Division\'s well layer (about 142,000 records), counted by the server: by status, and for the active wells by kind, county and operator. Counted here, never listed.',
};
