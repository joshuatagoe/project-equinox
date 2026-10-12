"""The app's one script (feat-14, D89): the order ticket prices again as you type.

It fetches the ticket's own page with the new order and swaps in the answer, so there is no
second way to price an order. Without it, the ticket's button does the same.
"""

SCRIPT = """
(() => {
  const form = document.querySelector("form[data-live]");
  if (!form) return;
  let timer = 0, asked = 0;
  const price = () => {
    const url = form.action + "?" + new URLSearchParams(new FormData(form));
    const mine = ++asked;
    document.getElementById("result")?.setAttribute("aria-busy", "true");
    fetch(url).then((r) => r.text()).then((text) => {
      if (mine !== asked) return;
      const fresh = new DOMParser().parseFromString(text, "text/html");
      for (const id of ["result", "same-bet"]) {
        const now = document.getElementById(id), next = fresh.getElementById(id);
        if (now && next) now.replaceWith(next);
      }
      history.replaceState(null, "", url);
    });
  };
  const later = (wait) => { clearTimeout(timer); timer = setTimeout(price, wait); };
  form.addEventListener("input", () => later(450));
  form.addEventListener("change", () => later(60));
  form.addEventListener("submit", (e) => { e.preventDefault(); later(0); });
})();
"""
