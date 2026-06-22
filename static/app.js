// Dashboard controller: opens a WebSocket, sends "start", and renders the live
// stream of step events into the log and screenshot panels.

(() => {
  "use strict";

  const runBtn = document.getElementById("run");
  const statusEl = document.getElementById("status");
  const statusLabel = document.getElementById("status-label");
  const logEl = document.getElementById("log");
  const logEmpty = document.getElementById("log-empty");
  const stepCounter = document.getElementById("step-counter");
  const screenshotEl = document.getElementById("screenshot");
  const viewportEmpty = document.getElementById("viewport-empty");
  const viewMeta = document.getElementById("view-meta");
  const modelEl = document.getElementById("model");
  const modelName = document.getElementById("model-name");

  let socket = null;
  let stepCount = 0;
  let lastRow = null;

  function setModel(name, switched) {
    if (!name) return;
    modelEl.hidden = false;
    modelName.textContent = name;
    if (switched) {
      modelEl.classList.add("switched");
      setTimeout(() => modelEl.classList.remove("switched"), 1200);
    }
  }

  function setStatus(state, label) {
    statusEl.dataset.state = state;
    statusLabel.textContent = label;
  }

  function showScreenshot(b64) {
    if (!b64) return;
    viewportEmpty.style.display = "none";
    screenshotEl.classList.add("visible");
    screenshotEl.style.opacity = "0.5";
    screenshotEl.src = "data:image/png;base64," + b64;
    requestAnimationFrame(() => {
      screenshotEl.style.opacity = "1";
    });
  }

  function formatTool(tool, input) {
    if (!input || Object.keys(input).length === 0) return tool + "()";
    const args = Object.entries(input)
      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
      .join(", ");
    return `${tool}(${args})`;
  }

  // Builds a step row and returns its badge so the action result can update it.
  function addStep(num, toolText, reasoning, badgeState, badgeText) {
    if (logEmpty) logEmpty.style.display = "none";

    const li = document.createElement("li");
    li.className = "step";

    const numEl = document.createElement("div");
    numEl.className = "step-num";
    numEl.textContent = num;

    const body = document.createElement("div");
    body.className = "step-body";

    const top = document.createElement("div");
    top.className = "step-top";

    const tool = document.createElement("span");
    tool.className = "step-tool";
    tool.textContent = toolText;

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.dataset.state = badgeState;
    badge.textContent = badgeText;

    top.appendChild(tool);
    top.appendChild(badge);
    body.appendChild(top);

    if (reasoning) {
      const reason = document.createElement("div");
      reason.className = "step-reason";
      reason.textContent = reasoning;
      body.appendChild(reason);
    }

    li.appendChild(numEl);
    li.appendChild(body);
    logEl.appendChild(li);
    logEl.scrollTop = logEl.scrollHeight;

    return badge;
  }

  function bumpCounter(n) {
    stepCount = n;
    stepCounter.textContent = `${n} step${n === 1 ? "" : "s"}`;
  }

  function handleEvent(msg) {
    if (msg.screenshot) showScreenshot(msg.screenshot);

    switch (msg.event) {
      case "start":
        setStatus("running", "Running");
        setModel(msg.model, false);
        break;

      case "model_switch":
        setModel(msg.to, true);
        addStep(
          msg.step || stepCount,
          `model → ${msg.to}`,
          msg.from ? `switched from ${msg.from} (rate limit)` : "",
          "info",
          "switch",
        );
        break;

      case "decision": {
        bumpCounter(msg.step);
        viewMeta.textContent = `step ${msg.step}`;
        if (msg.model) setModel(msg.model, false);
        lastRow = addStep(
          msg.step,
          formatTool(msg.tool, msg.input),
          msg.reasoning,
          "running",
          "running",
        );
        break;
      }

      case "action": {
        if (lastRow) {
          if (msg.success) {
            lastRow.dataset.state = "ok";
            lastRow.textContent = "ok";
          } else {
            lastRow.dataset.state = "fail";
            lastRow.textContent = "failed";
          }
          lastRow = null;
        }
        break;
      }

      case "no_action":
        addStep(msg.step, "— no tool call —", msg.reasoning, "info", "skipped");
        break;

      case "finish":
        addStep(msg.step, "task_complete", msg.summary, "done", "done");
        setStatus("done", "Done");
        break;

      case "max_steps":
        addStep(msg.steps, "max steps reached", "", "info", "stopped");
        setStatus("done", "Stopped");
        break;

      case "error":
        addStep(stepCount, "error", msg.detail, "fail", "error");
        setStatus("error", "Error");
        break;

      case "done":
        if (statusEl.dataset.state === "running") {
          const ok = msg.result && msg.result.status === "finished";
          setStatus(ok ? "done" : "error", ok ? "Done" : "Incomplete");
        }
        finishRun();
        break;

      default:
        break;
    }
  }

  function finishRun() {
    runBtn.disabled = false;
    runBtn.textContent = "Run Agent";
  }

  function run() {
    logEl.innerHTML = "";
    bumpCounter(0);
    lastRow = null;
    viewMeta.textContent = "—";
    runBtn.disabled = true;
    runBtn.textContent = "Running…";
    setStatus("running", "Connecting");

    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${location.host}/ws`);

    socket.addEventListener("open", () => {
      setStatus("running", "Running");
      socket.send(JSON.stringify({ action: "start" }));
    });

    socket.addEventListener("message", (e) => {
      try {
        handleEvent(JSON.parse(e.data));
      } catch (err) {
        console.error("bad event", err);
      }
    });

    socket.addEventListener("close", () => {
      if (statusEl.dataset.state === "running") {
        setStatus("error", "Disconnected");
      }
      finishRun();
    });

    socket.addEventListener("error", () => {
      setStatus("error", "Connection error");
      finishRun();
    });
  }

  runBtn.addEventListener("click", run);
})();
