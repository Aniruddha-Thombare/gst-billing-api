/** GST state / UT codes (01 to 38). The first 2 digits of a GSTIN are one of these. */
export const STATES: { code: string; name: string }[] = [
  ["01","Jammu & Kashmir"],["02","Himachal Pradesh"],["03","Punjab"],["04","Chandigarh"],["05","Uttarakhand"],["06","Haryana"],
  ["07","Delhi"],["08","Rajasthan"],["09","Uttar Pradesh"],["10","Bihar"],["11","Sikkim"],["12","Arunachal Pradesh"],["13","Nagaland"],
  ["14","Manipur"],["15","Mizoram"],["16","Tripura"],["17","Meghalaya"],["18","Assam"],["19","West Bengal"],["20","Jharkhand"],
  ["21","Odisha"],["22","Chhattisgarh"],["23","Madhya Pradesh"],["24","Gujarat"],["26","Dadra & Nagar Haveli and Daman & Diu"],
  ["27","Maharashtra"],["29","Karnataka"],["30","Goa"],["31","Lakshadweep"],["32","Kerala"],["33","Tamil Nadu"],["34","Puducherry"],
  ["35","Andaman & Nicobar"],["36","Telangana"],["37","Andhra Pradesh"],["38","Ladakh"],
].map(([code, name]) => ({ code, name }));

export const stateName = (code: string) => STATES.find((s) => s.code === code)?.name ?? code;

/** Statutory GST slabs, same list as the backend's tax engine. */
export const GST_SLABS = ["0","0.1","0.125","0.25","0.75","1","1.5","2.5","3","5","6","7.5","9","12","14","18","28","40"];
