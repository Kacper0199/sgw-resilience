(() => {
  const root = document.documentElement;
  try {
    const saved = localStorage.getItem("sgw.theme");
    const dark = saved ? saved === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "dark" : "light";
    if (localStorage.getItem("sgw.transparency") === "reduced") root.dataset.transparency = "reduced";
  } catch {
    root.dataset.theme = "light";
  }
})();
