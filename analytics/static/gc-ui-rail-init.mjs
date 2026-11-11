// Same-origin static bootstrap. The imported controller is pinned to GC UI source.
// Dashboard access remains controlled by the existing authenticated application.
import { initNavigationRail } from "./gc-ui-navigation-rail.mjs";
const rail = document.querySelector(".sidebar.gc-navigation-rail");
if (rail) {
  initNavigationRail(rail);
  const syncActive = () => {
    const selected = rail.querySelector('nav a[aria-current="page"]');
    for (const link of rail.querySelectorAll(".nav-item")) {
      link.classList.toggle("active",link === selected);
    }
  };
  window.addEventListener("hashchange",syncActive);
  window.addEventListener("popstate",syncActive);
  syncActive();
}
