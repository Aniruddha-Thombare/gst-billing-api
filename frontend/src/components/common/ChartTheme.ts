/** Chart colours. Recharts draws SVG, so it needs real colour values rather than Tailwind classes. */
export const CHART = { primary: "#5b50e6", teal: "#14b8a6", amber: "#f59e0b", rose: "#f43f5e", sky: "#0ea5e9", grid: "#e5e7eb" };
export const compactNumber = (n: number) => new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n);
