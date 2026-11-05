// Theme values for canvas drawing, read once from the CSS variables that
// src/theme.css (@theme) defines, so the canvases and the HTML share one palette.
const css = getComputedStyle(document.documentElement);
const v = (name: string) => css.getPropertyValue(`--${name}`).trim();

export const T = {
  paper: v("color-paper"),
  paper2: v("color-paper-2"),
  fg: v("color-fg"),
  muted: v("color-muted"),
  line: v("color-line"),
  grid: v("color-grid"),
  link: v("color-link"),
  ok: v("color-ok"),
  warn: v("color-warn"),
  bad: v("color-bad"),
  ch: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`color-ch${i}`)),
  mono: v("font-mono"),
  sans: v("font-sans"),
};

/** Canvas font string in the page's sans or mono face. */
export const font = (px: number, face: "sans" | "mono" = "sans") => `${px}px ${face === "mono" ? T.mono : T.sans}`;
