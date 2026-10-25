/* Fluid motion primitives for Yalendar.
 *
 * Springs rather than CSS transitions, because gesture-driven motion has to be
 * grabbable mid-flight: a spring animates from wherever the element actually is
 * and carries its velocity through a re-target, so interrupting it never jumps.
 *
 * Parameters follow Apple's designer-facing pair rather than mass/stiffness/
 * damping: `damping` is the damping ratio (1 = critically damped, no overshoot)
 * and `response` is roughly how long it takes to reach the target, in seconds.
 */
(function (global) {
  "use strict";

  var reduceMotion = global.matchMedia
    ? global.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

  /** A single scalar spring. Decompose 2D motion into two of these: one spring
   *  on a 2D distance desyncs when the axes have different velocities. */
  function Spring(value, options) {
    options = options || {};
    this.value = value || 0;
    this.target = this.value;
    this.velocity = 0;
    this.damping = options.damping == null ? 1.0 : options.damping;
    this.response = options.response == null ? 0.4 : options.response;
    this.onUpdate = options.onUpdate || null;
    this.onRest = options.onRest || null;
    this._raf = 0;
    this._last = 0;
  }

  Spring.prototype.configure = function (damping, response) {
    if (damping != null) this.damping = damping;
    if (response != null) this.response = response;
    return this;
  };

  /** Re-target. Velocity is preserved unless explicitly replaced, which is what
   *  keeps a reversal from hitting a "brick wall" of discontinuous motion. */
  Spring.prototype.set = function (target, velocity) {
    this.target = target;
    if (velocity != null) this.velocity = velocity;
    if (reduceMotion.matches) {
      // Non-vestibular equivalent: arrive immediately, let opacity carry it.
      this.value = target;
      this.velocity = 0;
      if (this.onUpdate) this.onUpdate(this.value, this);
      if (this.onRest) this.onRest(this);
      return this;
    }
    this._start();
    return this;
  };

  /** Snap without animating — used when a gesture takes over. */
  Spring.prototype.jump = function (value) {
    this.stop();
    this.value = value;
    this.target = value;
    this.velocity = 0;
    if (this.onUpdate) this.onUpdate(this.value, this);
    return this;
  };

  Spring.prototype.stop = function () {
    if (this._raf) global.cancelAnimationFrame(this._raf);
    this._raf = 0;
    return this;
  };

  Spring.prototype._start = function () {
    if (this._raf) return;
    this._last = global.performance.now();
    var self = this;
    var step = function (now) {
      var dt = Math.min((now - self._last) / 1000, 1 / 30); // clamp after a stall
      self._last = now;
      self._integrate(dt);
      if (self.onUpdate) self.onUpdate(self.value, self);
      if (Math.abs(self.velocity) < 0.08 && Math.abs(self.target - self.value) < 0.08) {
        self.value = self.target;
        self.velocity = 0;
        self._raf = 0;
        if (self.onUpdate) self.onUpdate(self.value, self);
        if (self.onRest) self.onRest(self);
        return;
      }
      self._raf = global.requestAnimationFrame(step);
    };
    this._raf = global.requestAnimationFrame(step);
  };

  Spring.prototype._integrate = function (dt) {
    // omega = 2*pi/response; k = omega^2; c = 2*zeta*omega
    var omega = (2 * Math.PI) / Math.max(this.response, 0.0001);
    var k = omega * omega;
    var c = 2 * this.damping * omega;
    // Substep so a long frame cannot make the spring explode.
    var steps = Math.max(1, Math.ceil(dt / (1 / 240)));
    var h = dt / steps;
    for (var i = 0; i < steps; i += 1) {
      var a = -k * (this.value - this.target) - c * this.velocity;
      this.velocity += a * h;
      this.value += this.velocity * h;
    }
  };

  /** Where a flick would come to rest. Apple's exponential-decay projection
   *  from Designing Fluid Interfaces - not the v^2/(2a) textbook form. */
  function project(velocity, decelerationRate) {
    var d = decelerationRate == null ? 0.998 : decelerationRate;
    return ((velocity / 1000) * d) / (1 - d);
  }

  /** Progressive resistance past a boundary: real things slow before stopping. */
  function rubberband(overshoot, dimension, constant) {
    var c = constant == null ? 0.55 : constant;
    if (!dimension) return overshoot * c;
    return (overshoot * dimension * c) / (dimension + c * Math.abs(overshoot));
  }

  /** Short pointer history, so release velocity reflects the last few moves
   *  rather than one noisy sample. */
  function Tracker() {
    this.samples = [];
  }
  Tracker.prototype.reset = function (value) {
    this.samples = [{ v: value, t: global.performance.now() }];
  };
  Tracker.prototype.push = function (value) {
    this.samples.push({ v: value, t: global.performance.now() });
    if (this.samples.length > 6) this.samples.shift();
  };
  Tracker.prototype.velocity = function () {
    if (this.samples.length < 2) return 0;
    var last = this.samples[this.samples.length - 1];
    var first = this.samples[0];
    for (var i = this.samples.length - 1; i >= 0; i -= 1) {
      if (last.t - this.samples[i].t > 30) { first = this.samples[i]; break; }
    }
    var dt = (last.t - first.t) / 1000;
    if (dt <= 0) return 0;
    return (last.v - first.v) / dt;
  };

  /** Feedback on pointer-DOWN, not on click. Waiting for release feels dead.
   *  Cancellable by dragging away, per the gesture checklist. */
  function pressable(root, selector) {
    root.addEventListener("pointerdown", function (event) {
      var el = event.target.closest(selector);
      if (!el || el.dataset.noPress === "1") return;
      el.classList.add("is-pressed");
      var release = function () {
        el.classList.remove("is-pressed");
        global.removeEventListener("pointerup", release, true);
        global.removeEventListener("pointercancel", release, true);
      };
      global.addEventListener("pointerup", release, true);
      global.addEventListener("pointercancel", release, true);
    }, { passive: true });
  }

  global.Fluid = {
    Spring: Spring,
    Tracker: Tracker,
    project: project,
    rubberband: rubberband,
    pressable: pressable,
    get reduceMotion() { return reduceMotion.matches; },
  };
})(window);
