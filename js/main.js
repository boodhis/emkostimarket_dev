(function () {
  var b = document.getElementById("burger");
  var n = document.getElementById("nav");
  if (b && n) {
    b.addEventListener("click", function () {
      var open = n.classList.toggle("open");
      b.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // галерея товара
  var main = document.querySelector(".main-pic-img");
  document.querySelectorAll(".thumb").forEach(function (t) {
    t.addEventListener("click", function () {
      var full = t.getAttribute("data-full");
      if (main && full) {
        main.src = full;
        document.querySelectorAll(".thumb").forEach(function (x) { x.classList.remove("on"); });
        t.classList.add("on");
      }
    });
  });
})();
