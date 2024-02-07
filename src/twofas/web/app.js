// helpers.ts
function setIntervalImmediately(func, interval) {
  func();
  return setInterval(func, interval);
}
function render_template(template_id, variables) {
  const template = document.getElementById(template_id);
  if (!template) {
    throw `Template ${template} not found.`;
  }
  let content = template.innerHTML;
  content = content.replace(/\${(.*?)}/g, (_, variable) => {
    return variables[variable.trim()] ?? "";
  });
  const tmp_container = document.createElement("div");
  tmp_container.innerHTML = content;
  return tmp_container.firstElementChild ?? tmp_container;
}
async function auth_details_to_totp_entry(idx, service) {
  const image = await Python.load_image(service.icon.iconCollection.id);
  return {
    icon_id: service.icon.iconCollection.id,
    service: service.name,
    username: service.otp.account ?? service.otp.label ?? "",
    idx,
    image
  };
}
function current_countdown_value() {
  return 30 - Math.round(new Date().getTime() / 1000) % 30;
}
function totp_format(code) {
  return code.match(/.{1,3}/g)?.join(" ") ?? code;
}
function copy_current_code($code_holder) {
  const current_code = $code_holder.dataset.code;
  if (current_code) {
    navigator.clipboard.writeText(current_code);
  } else {
    console.error("No current code?");
  }
}

// app.ts
var new_totp_entry = function(data, secret) {
  const entry = render_template("totp-entry", data);
  $totp_holder.appendChild(entry);
  Object.assign(entry.dataset, {
    idx: data.idx,
    icon_id: data.icon_id,
    service: data.service.toLowerCase(),
    username: data.username?.toLowerCase() ?? ""
  });
  const $code_holder = entry.querySelector(".entry-code");
  entry.addEventListener("click", (event) => {
    const idx = entry.dataset.idx;
    window.location.href = `entry.html?idx=${idx}`;
  });
  let t = 0;
  $code_holder.addEventListener("click", async (event) => {
    clearTimeout(t);
    $code_holder.classList.add("active");
    t = setTimeout(() => {
      $code_holder.classList.remove("active");
    }, 1000);
    copy_current_code($code_holder);
    event.stopPropagation();
  });
  setIntervalImmediately(async () => {
    const code = await Python.totp(secret);
    const formatted = totp_format(code);
    $code_holder.dataset.code = code;
    $code_holder.innerHTML = formatted;
  }, 1000);
};
var fix_missing_icons = function() {
  const missing_imgs = document.querySelectorAll('.totp-entry img[src=""]');
  if (missing_imgs.length) {
    console.debug(`Try to fix ${missing_imgs.length} images.`);
  } else {
    console.debug(`No missing images!`);
  }
  missing_imgs.forEach(async ($img) => {
    const icon_id = $img.dataset.icon;
    if (!icon_id) {
      return;
    }
    const img = await Python.load_image(icon_id);
    $img.src = img;
  });
};
var hello = function() {
  console.debug("Python says hello!");
  Python.hello();
};
var python_task_started = function(task) {
  console.debug(`${task} started in Python.`);
};
async function python_task_completed(task) {
  console.debug(`${task} completed in Python.`);
  if (task === "load_icons") {
    fix_missing_icons();
  }
}
var update_countdown = function() {
  const value = String(current_countdown_value());
  document.querySelectorAll(".counter-circle").forEach(($counter) => {
    $counter.innerHTML = value;
  });
};
async function init_services() {
  const services = await Python.get_services();
  const promises = services.map(async (service, idx) => {
    const entry = await auth_details_to_totp_entry(idx, service);
    new_totp_entry(entry, service.secret);
    return true;
  });
  Promise.all(promises).then(apply_alternating_background_colors);
}
var apply_alternating_background_colors = function() {
  const entries = document.querySelectorAll(".totp-entry:not(.hidden)");
  entries.forEach(function(entry, index) {
    if (index % 2 === 0) {
      entry.style.backgroundColor = "var(--light-bg)";
    } else {
      entry.style.backgroundColor = "var(--dark-bg)";
    }
  });
};
var search = function(_) {
  const query = $search.value.toLowerCase();
  const entries = document.querySelectorAll(".totp-entry");
  entries.forEach((entry) => {
    let matches = !query || entry.dataset.service?.includes(query) || entry.dataset.username?.includes(query);
    entry.classList.toggle("hidden", !matches);
  });
  apply_alternating_background_colors();
};
async function setup_search() {
  $search.addEventListener("change", search);
  $search.addEventListener("keyup", search);
  document.addEventListener("keydown", (_) => {
    $search.focus();
  });
}
async function main() {
  setIntervalImmediately(update_countdown, 1000);
  await init_services();
  await setup_search();
}
var $totp_holder = document.getElementById("totp-holder");
eel.expose(hello);
eel.expose(python_task_started);
eel.expose(python_task_completed, "python_task_completed");
var $search = document.getElementById("search");
main();
