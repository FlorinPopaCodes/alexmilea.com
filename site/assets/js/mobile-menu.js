(function () {
  var menuOpenClass = "header--menu-open";

  function getButtons() {
    return Array.prototype.slice.call(
      document.querySelectorAll('[data-test="header-burger"]')
    );
  }

  function syncMenuState(isOpen) {
    var menu = document.querySelector(".header-menu");

    document.body.classList.toggle(menuOpenClass, isOpen);

    if (menu) {
      menu.setAttribute("aria-hidden", String(!isOpen));
    }

    getButtons().forEach(function (button) {
      button.classList.toggle("burger--active", isOpen);
      button.setAttribute("aria-expanded", String(isOpen));

      var openLabel = button.querySelector(".js-header-burger-open-title");
      var closeLabel = button.querySelector(".js-header-burger-close-title");

      if (openLabel) {
        openLabel.hidden = isOpen;
      }

      if (closeLabel) {
        closeLabel.hidden = !isOpen;
      }
    });
  }

  function toggleMenu() {
    syncMenuState(!document.body.classList.contains(menuOpenClass));
  }

  function initMobileMenu() {
    var menu = document.querySelector(".header-menu");
    var buttons = getButtons();

    if (!menu || buttons.length === 0) {
      return;
    }

    menu.setAttribute("id", menu.id || "mobile-menu");
    menu.setAttribute("aria-hidden", "true");

    buttons.forEach(function (button) {
      button.setAttribute("type", "button");
      button.setAttribute("aria-controls", menu.id);
      button.setAttribute("aria-expanded", "false");
      button.addEventListener("click", toggleMenu);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        syncMenuState(false);
      }
    });

    menu.addEventListener("click", function (event) {
      var link = event.target.closest("a");

      if (link && link.origin === window.location.origin) {
        syncMenuState(false);
      }
    });

    syncMenuState(false);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMobileMenu);
  } else {
    initMobileMenu();
  }
})();
