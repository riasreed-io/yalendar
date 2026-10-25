/* Ask Yalendar - chat assistant.
 *
 * On narrow screens the panel is a sheet you can actually grab: it tracks the
 * finger 1:1, resists past the top edge, and on release projects where the
 * flick was heading rather than snapping from the lift-off point. The spring
 * takes over at exactly the release velocity, so there is no seam between
 * dragging and animating, and the sheet can be caught again mid-flight.
 *
 * Without JavaScript the form is a plain GET to /ask, which the server renders.
 */
(function () {
  "use strict";

  var form = document.getElementById("ask-form");
  var input = document.getElementById("ask-input");
  var chat = document.getElementById("chat");
  var examples = document.getElementById("ask-examples");
  var dock = document.getElementById("chat-dock");
  var launch = document.getElementById("chat-launch");
  var closeBtn = document.getElementById("chat-close");
  var grabber = document.getElementById("chat-grabber");
  var tpl = document.getElementById("tpl-hit");
  if (!form || !input || !chat) return;

  var F = window.Fluid;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* ---------------------------------------------------------- the sheet */

  var sheet = null;
  if (dock && dock.dataset.dock && F) {
    sheet = (function () {
      var height = 0;
      var open = false;
      var dragging = false;
      var spring = new F.Spring(0, { damping: 1.0, response: 0.4 });
      var tracker = new F.Tracker();
      var grabOffset = 0;

      function measure() {
        height = dock.offsetHeight || 420;
      }

      spring.onUpdate = function (y) {
        dock.style.transform = "translate3d(0," + y + "px,0)";
        // Scrim tracks the sheet 1:1 rather than fading on a timer.
        var progress = height ? 1 - Math.min(Math.max(y / height, 0), 1) : 0;
        document.documentElement.style.setProperty("--sheet-progress", progress.toFixed(3));
      };

      function setOpen(next, velocity) {
        measure();
        open = next;
        dock.classList.toggle("open", next);
        document.body.classList.toggle("chat-open", next);
        if (launch) launch.setAttribute("aria-expanded", next ? "true" : "false");
        // A flick carried momentum, so a little overshoot reads as physical;
        // a tap did not, so it settles without bounce.
        spring.configure(velocity ? 0.8 : 1.0, 0.35);
        spring.set(next ? 0 : height, velocity);
        if (next) {
          try { input.focus({ preventScroll: true }); } catch (e) { input.focus(); }
        } else if (launch) {
          launch.focus();
        }
      }

      function onDown(event) {
        if (event.button != null && event.button !== 0) return;
        // Let the conversation scroll normally; only chrome starts a drag.
        measure();
        dragging = true;
        // Start from where it IS, not where it was heading - this is what
        // makes grabbing a moving sheet feel continuous.
        spring.stop();
        grabOffset = event.clientY - spring.value;
        tracker.reset(event.clientY);
        dock.classList.add("dragging");
        event.currentTarget.setPointerCapture(event.pointerId);
      }

      function onMove(event) {
        if (!dragging) return;
        tracker.push(event.clientY);
        var y = event.clientY - grabOffset;
        if (y < 0) y = -F.rubberband(-y, height); // resist past fully-open
        spring.jump(Math.min(y, height * 1.2));
      }

      function onUp(event) {
        if (!dragging) return;
        dragging = false;
        dock.classList.remove("dragging");
        try { event.currentTarget.releasePointerCapture(event.pointerId); } catch (e) {}
        var velocity = tracker.velocity();
        // Decide from where the flick is GOING, not where the finger left.
        // 0.99, not the 0.998 scroll rate: over a sheet's short travel the
        // scroll rate projects ~100px even for a gentle drag, so it cannot
        // tell a slow nudge from a flick and closes on both.
        var projected = spring.value + F.project(velocity, 0.99);
        var shouldClose = projected > height * 0.5;
        setOpen(!shouldClose, velocity);
      }

      function bindDrag(node) {
        if (!node) return;
        node.addEventListener("pointerdown", onDown);
        node.addEventListener("pointermove", onMove);
        node.addEventListener("pointerup", onUp);
        node.addEventListener("pointercancel", onUp);
      }

      measure();
      spring.jump(height);
      window.addEventListener("resize", function () {
        measure();
        if (!open && !dragging) spring.jump(height);
      });

      return {
        bindDrag: bindDrag,
        toggle: function () { setOpen(!open); },
        close: function () { setOpen(false); },
        isOpen: function () { return open; },
      };
    })();

    sheet.bindDrag(grabber);
    sheet.bindDrag(document.getElementById("chat-dock-head"));
  }

  /* ------------------------------------------------------- conversation */

  function bubble(kind) {
    var node = el("div", "bubble " + kind);
    chat.appendChild(node);
    chat.scrollTop = chat.scrollHeight;
    return node;
  }

  function render(node, data) {
    node.textContent = "";
    node.appendChild(el("p", null, data.reply));

    if (data.events && data.events.length) {
      var list = el("ul", "hits");
      data.events.forEach(function (event) {
        var item = tpl.content.cloneNode(true);
        item.querySelector(".dot").classList.add(event.channel || "public");
        item.querySelector(".hit-when").textContent = event.when;
        var title = item.querySelector(".hit-title");
        title.textContent = event.title;
        if (event.url) {
          title.href = event.url;
        } else {
          title.replaceWith(el("span", "hit-title", event.title));
        }
        var meta = [event.org, event.location].filter(Boolean).join(" · ");
        item.querySelector(".hit-meta").textContent = meta;
        list.appendChild(item);
      });
      node.appendChild(list);
      if (data.more) node.appendChild(el("p", "hit-more", "and " + data.more + " more"));
    }

    if (data.suggestions && data.suggestions.length) {
      var wrap = el("div", "chips-inline");
      data.suggestions.forEach(function (idea) {
        var chip = el("a", "chip", idea);
        chip.href = "/ask?q=" + encodeURIComponent(idea);
        chip.addEventListener("click", function (ev) { ev.preventDefault(); send(idea); });
        wrap.appendChild(chip);
      });
      node.appendChild(wrap);
    }

    if (data.link && data.events && data.events.length) {
      var link = el("a", "hit-link", (data.link_label || "Open in the calendar") + " →");
      link.href = data.link;
      node.appendChild(link);
    }
    chat.scrollTop = chat.scrollHeight;
  }

  function send(question) {
    question = (question || "").trim();
    if (!question) return;
    bubble("me").appendChild(el("p", null, question));
    input.value = "";
    var pending = bubble("bot typing");
    var dots = el("span", "dots");
    dots.appendChild(el("span"));
    dots.appendChild(el("span"));
    pending.appendChild(dots);

    var body = new FormData();
    body.append("q", question);
    fetch("/ask", { method: "POST", body: body, headers: { Accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error(res.status);
        return res.json();
      })
      .then(function (data) {
        pending.classList.remove("typing");
        render(pending, data);
      })
      .catch(function () {
        pending.classList.remove("typing");
        pending.textContent = "";
        pending.appendChild(el("p", null,
          "Something went wrong reaching the calendar. Try again in a moment."));
      });
  }

  form.addEventListener("submit", function (ev) { ev.preventDefault(); send(input.value); });

  if (examples) {
    examples.addEventListener("click", function (ev) {
      var chip = ev.target.closest(".chip");
      if (!chip) return;
      ev.preventDefault();
      send(chip.textContent.trim());
    });
  }

  if (launch) launch.addEventListener("click", function () { if (sheet) sheet.toggle(); });
  if (closeBtn) closeBtn.addEventListener("click", function () { if (sheet) sheet.close(); });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && sheet && sheet.isOpen()) sheet.close();
  });

  if (!dock || !dock.dataset.dock) {
    if (chat.querySelectorAll(".bubble").length < 2) {
      try { input.focus({ preventScroll: true }); } catch (e) { input.focus(); }
    }
  }
})();
