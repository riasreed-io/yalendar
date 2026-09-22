/* Ask Yalendar - chat assistant.
   Works on the standalone /ask page and in the panel docked beside the
   calendar. Progressive enhancement: without this file the form is a plain
   GET to /ask, which the server renders. */
(function () {
  var form = document.getElementById("ask-form");
  var input = document.getElementById("ask-input");
  var chat = document.getElementById("chat");
  var examples = document.getElementById("ask-examples");
  var dock = document.getElementById("chat-dock");
  var launch = document.getElementById("chat-launch");
  var close = document.getElementById("chat-close");
  var tpl = document.getElementById("tpl-hit");
  if (!form || !input || !chat) return;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

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
      if (data.more) {
        node.appendChild(el("p", "hit-more", "and " + data.more + " more"));
      }
    }

    if (data.suggestions && data.suggestions.length) {
      var wrap = el("div", "chips-inline");
      data.suggestions.forEach(function (idea) {
        var chip = el("a", "chip", idea);
        chip.href = "/ask?q=" + encodeURIComponent(idea);
        chip.addEventListener("click", function (ev) {
          ev.preventDefault();
          send(idea);
        });
        wrap.appendChild(chip);
      });
      node.appendChild(wrap);
    }

    if (data.link && data.events && data.events.length) {
      var link = el("a", "hit-link",
        (data.link_label || "Open in the calendar") + " →");
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
    pending.appendChild(el("span", "dots"));

    var body = new FormData();
    body.append("q", question);
    fetch("/ask", {
      method: "POST",
      body: body,
      headers: { "Accept": "application/json" }
    })
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

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    send(input.value);
  });

  if (examples) {
    examples.addEventListener("click", function (ev) {
      var chip = ev.target.closest(".chip");
      if (!chip) return;
      ev.preventDefault();
      send(chip.textContent.trim());
    });
  }

  /* Docked panel: on narrow screens it is hidden behind a launcher so the
     calendar keeps the full width it had before. */
  function setOpen(open) {
    if (!dock) return;
    dock.classList.toggle("open", open);
    // Hides the launcher while the panel covers it, so the two round
    // buttons do not stack in the same corner.
    document.body.classList.toggle("chat-open", open);
    if (launch) launch.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      try { input.focus({ preventScroll: true }); } catch (e) { input.focus(); }
    } else if (launch) {
      launch.focus();
    }
  }

  if (launch) {
    launch.addEventListener("click", function () {
      setOpen(!dock.classList.contains("open"));
    });
  }
  if (close) {
    close.addEventListener("click", function () { setOpen(false); });
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && dock && dock.classList.contains("open")) {
      setOpen(false);
    }
  });

  // Only steal focus on the standalone page, and only with nothing to read.
  if (!dock || !dock.dataset.dock) {
    if (chat.querySelectorAll(".bubble").length < 2) {
      try { input.focus({ preventScroll: true }); } catch (e) { input.focus(); }
    }
  }
})();
