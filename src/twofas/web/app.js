"use strict";
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
function render_template(template_id, variables) {
    var _a;
    const template = document.getElementById(template_id);
    if (!template) {
        throw `Template ${template} not found.`;
    }
    console.log({
        template,
        template_id,
        variables,
    });
    // Get the template content
    let content = template.innerHTML;
    // Interpolate variables into template content
    content = content.replace(/\${(.*?)}/g, (_, variable) => {
        var _a;
        return (_a = variables[variable.trim()]) !== null && _a !== void 0 ? _a : "";
    });
    // Create a temporary container to hold the parsed HTML
    const tmp_container = document.createElement("div");
    tmp_container.innerHTML = content;
    // Get the template content after interpolation
    return (_a = tmp_container.firstElementChild) !== null && _a !== void 0 ? _a : tmp_container; // contents OR empty div
}
const $totp_holder = document.getElementById("totp-holder");
function new_totp_entry(data) {
    const entry = render_template("totp-entry", data);
    $totp_holder.appendChild(entry);
}
// for (let i = 0; i < 20; i++) {
//   let data = {
//     service: "Wordpress",
//     username: "Henk",
//     code: String(i),
//     countdown: 3,
//   };
//   new_totp_entry(data);
// }
function new_image(b64) {
    const $image = new Image();
    $image.src = b64;
    return $image;
}
function new_row($image) {
    const $row = document.createElement("div");
    $row.appendChild($image);
    return $row;
}
const $imageholder = document.getElementById("imageholder");
function to_holder($row) {
    return $imageholder.appendChild($row);
}
function hello() {
    console.debug("Python says hello!");
    Python.hello();
}
eel.expose(hello);
function python_task_started(task) {
    console.debug(`${task} started in Python.`);
}
eel.expose(python_task_started);
function python_task_completed(task) {
    return __awaiter(this, void 0, void 0, function* () {
        console.debug(`${task} completed in Python.`);
        if (task === "load_icons") {
            // github icon
            Python.load_image("fff32440-f5be-4b9c-b471-f37d421f10c3")
                .then(new_image)
                .then(new_row)
                .then(to_holder);
            // wordpress icon
            Python.load_image("708df726-fb8b-4c01-8990-f2da0cd33839")
                .then(new_image)
                .then(new_row)
                .then(to_holder);
        }
    });
}
eel.expose(python_task_completed, "python_task_completed");
function main() {
    return __awaiter(this, void 0, void 0, function* () {
        // todo: check password/auth
        const services = yield Python.get_services();
        console.log({
            services,
        });
    });
}
main();
