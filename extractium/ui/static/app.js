/*
This file is part of Extractium™
extractium/ui/static/app.js
Author(s): Gabriel Mongefranco.
Created: 2026-09-28
Last Modified: 2026-09-28
Summary: The local page's script. Reads the session token from the
address the terminal printed, asks the server what state the settings
file is in, and shows one of three views: the welcome screen that
writes a first file, the settings form built from the description the
server sends, or the file's own text. Every value shown comes from the
settings file and is written into the page as text, never as markup.
The page checks in with the server while it is open, so the server
knows to keep running, and asks it to quit on the Quit button.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License along
with this program. If not, see <https://www.gnu.org/licenses/>.
*/

(function () {
  "use strict";

  /* ### Constants ### */

  var TOKEN_HEADER = "X-Extractium-Token";
  var TOKEN_STORAGE_KEY = "extractium-session-token";
  var CONFIGURATION_DOCS = "https://github.com/DepressionCenter/extractium/blob/main/docs/configuration.md";

  var token = readToken();
  var schema = null;
  var state = null;
  var settings = null;
  var pingTimer = null;

  /* ### Helpers ### */

  function byId(id) {
    return document.getElementById(id);
  }

  function element(tag, attributes, children) {
    var node = document.createElement(tag);
    Object.keys(attributes || {}).forEach(function (name) {
      if (name === "text") {
        node.textContent = attributes[name];
      } else if (name === "checked" || name === "disabled" || name === "required" || name === "hidden") {
        node[name] = Boolean(attributes[name]);
      } else {
        node.setAttribute(name, attributes[name]);
      }
    });
    (children || []).forEach(function (child) {
      node.appendChild(child);
    });
    return node;
  }

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  // The token travels in the fragment of the address the terminal
  // printed, which a browser never sends to a server or records in a
  // referrer. It is kept for this tab so a reload keeps working.
  function readToken() {
    var match = /(?:^|[#&])token=([^&]+)/.exec(window.location.hash);
    if (match) {
      try {
        window.sessionStorage.setItem(TOKEN_STORAGE_KEY, match[1]);
      } catch (error) {
        // Storage may be unavailable; the fragment alone still works.
      }
      return match[1];
    }
    try {
      return window.sessionStorage.getItem(TOKEN_STORAGE_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function api(method, path, payload) {
    var options = {method: method, headers: {}, credentials: "same-origin"};
    options.headers[TOKEN_HEADER] = token;
    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    return window.fetch(path, options).then(function (response) {
      return response.text().then(function (text) {
        var body = null;
        try {
          body = text ? JSON.parse(text) : null;
        } catch (error) {
          body = {error: "The server sent an answer the page could not read."};
        }
        return {status: response.status, body: body};
      });
    });
  }

  function say(text) {
    var status = byId("status");
    var error = byId("error");
    error.hidden = true;
    status.textContent = text;
    status.hidden = !text;
  }

  function complain(text) {
    var status = byId("status");
    var error = byId("error");
    status.hidden = true;
    error.textContent = text;
    error.hidden = !text;
    if (text) {
      error.focus && error.setAttribute("tabindex", "-1");
      error.focus();
    }
  }

  function show(sectionId) {
    ["no-token", "welcome", "settings"].forEach(function (id) {
      byId(id).hidden = id !== sectionId;
    });
    var heading = byId(sectionId + "-heading");
    if (heading) {
      heading.focus();
    }
  }

  function busy(button, isBusy) {
    button.disabled = isBusy;
  }

  /* ### Fields ### */

  // One field of the form. Returns the wrapper to place and a reader
  // that gives the typed value, or undefined for a blank field.
  function buildField(field, value, idPrefix) {
    var id = idPrefix + "-" + field.key;
    var helpId = id + "-help";
    var wrapper = element("div", {"class": "field"});
    var control;
    var read;

    if (field.kind === "boolean") {
      control = element("input", {type: "checkbox", id: id, "aria-describedby": helpId});
      control.checked = value === undefined || value === null ? Boolean(field["default"]) : Boolean(value);
      wrapper.appendChild(element("label", {"class": "checkbox-label", "for": id}, [
        control, element("span", {text: field.label})
      ]));
      read = function () {
        return control.checked;
      };
    } else if (field.kind === "choice") {
      control = element("select", {id: id, "aria-describedby": helpId});
      field.choices.forEach(function (choice) {
        control.appendChild(element("option", {value: choice, text: choice}));
      });
      control.value = value === undefined || value === null ? String(field["default"] || "") : String(value);
      wrapper.appendChild(element("label", {"for": id, text: field.label}));
      wrapper.appendChild(control);
      read = function () {
        return control.value || undefined;
      };
    } else if (field.kind === "lines") {
      control = element("textarea", {id: id, rows: "3", "aria-describedby": helpId, spellcheck: "false"});
      control.value = Array.isArray(value) ? value.join("\n") : (value === undefined || value === null ? "" : String(value));
      wrapper.appendChild(element("label", {"for": id, text: field.label}));
      wrapper.appendChild(control);
      var emptyBox = null;
      if (field.emptyList) {
        var emptyId = id + "-empty";
        emptyBox = element("input", {type: "checkbox", id: emptyId});
        emptyBox.checked = Array.isArray(value) && value.length === 0;
        wrapper.appendChild(element("label", {"class": "checkbox-label", "for": emptyId}, [
          emptyBox, element("span", {text: "Leave the list empty on purpose, to " + field.emptyList})
        ]));
      }
      read = function () {
        var lines = control.value.split("\n").map(function (line) {
          return line.trim();
        }).filter(function (line) {
          return line.length > 0;
        });
        if (lines.length > 0) {
          return lines;
        }
        return emptyBox && emptyBox.checked ? [] : undefined;
      };
    } else {
      var type = field.kind === "integer" || field.kind === "number" ? "number" : "text";
      var attributes = {type: type, id: id, "aria-describedby": helpId, autocomplete: "off"};
      if (field.kind === "integer") {
        attributes.step = "1";
      } else if (field.kind === "number") {
        attributes.step = "any";
      }
      if (field.required) {
        attributes.required = true;
      }
      control = element("input", attributes);
      control.value = value === undefined || value === null ? "" : String(value);
      if (field["default"] !== null && field["default"] !== undefined && type === "text") {
        control.placeholder = String(field["default"]);
      }
      wrapper.appendChild(element("label", {"for": id, text: field.label}));
      wrapper.appendChild(control);
      read = function () {
        var text = control.value.trim();
        if (!text) {
          return undefined;
        }
        if (field.kind === "integer" || field.kind === "number") {
          var number = Number(text);
          return isNaN(number) ? text : number;
        }
        return text;
      };
    }

    var helpText = field.help;
    if (field["default"] !== null && field["default"] !== undefined && field.kind !== "boolean" && field.kind !== "lines") {
      helpText += " Default: " + String(field["default"]) + ".";
    }
    wrapper.appendChild(element("p", {"class": "help", id: helpId, text: helpText}));
    return {node: wrapper, read: read, key: field.key};
  }

  /* ### Sources And Outputs ### */

  // One entry of the sources or outputs list: a type chooser, the
  // fields every entry has, and the fields its type takes. Keys the
  // form does not know, such as a plug-in's own options, travel back
  // unchanged.
  function buildEntry(kind, entry, position, types, commonFields, onRemove) {
    var prefix = kind + "-" + position;
    var typeNames = Object.keys(types);
    var typeName = typeof entry.type === "string" ? entry.type : (kind === "source" ? "web" : "container");
    var known = Object.prototype.hasOwnProperty.call(types, typeName);
    var readers = [];
    var fieldsBox = element("div");

    var select = element("select", {id: prefix + "-type", "aria-describedby": prefix + "-type-help"});
    typeNames.forEach(function (name) {
      select.appendChild(element("option", {value: name, text: types[name].label + " (" + name + ")"}));
    });
    if (!known) {
      select.appendChild(element("option", {value: typeName, text: typeName + " (from a plug-in)"}));
    }
    select.value = typeName;
    var typeHelp = element("p", {"class": "help", id: prefix + "-type-help"});

    var legendText = (kind === "source" ? "Source " : "Output ") + position;
    var fieldset = element("fieldset", {}, [element("legend", {text: legendText})]);
    var head = element("div", {"class": "entry-head"}, [
      element("div", {"class": "field"}, [
        element("label", {"for": prefix + "-type", text: "Type"}), select, typeHelp
      ]),
      element("button", {type: "button", "class": "secondary", text: "Remove " + legendText.toLowerCase()})
    ]);
    head.lastChild.addEventListener("click", onRemove);
    fieldset.appendChild(head);
    fieldset.appendChild(fieldsBox);

    function renderFields() {
      clear(fieldsBox);
      readers = [];
      var chosen = select.value;
      var description = types[chosen];
      typeHelp.textContent = description ? description.help
        : "This type comes from a plug-in. Its options are kept as the file holds them; change them in the advanced view.";
      commonFields.forEach(function (field) {
        var built = buildField(field, entry[field.key], prefix);
        readers.push(built);
        fieldsBox.appendChild(built.node);
      });
      (description ? description.fields : []).forEach(function (field) {
        var built = buildField(field, entry[field.key], prefix);
        readers.push(built);
        fieldsBox.appendChild(built.node);
      });
    }

    select.addEventListener("change", renderFields);
    renderFields();

    return {
      node: fieldset,
      read: function () {
        var chosen = select.value;
        var written = {};
        var knownKeys = {type: true};
        commonFields.forEach(function (field) {
          knownKeys[field.key] = true;
        });
        (types[chosen] ? types[chosen].fields : []).forEach(function (field) {
          knownKeys[field.key] = true;
        });
        // A plug-in's options come back as they were. A built-in type's
        // fields are rewritten from the form, and an option that
        // belonged to the previous type is dropped with it.
        if (!types[chosen]) {
          Object.keys(entry).forEach(function (key) {
            if (!knownKeys[key]) {
              written[key] = entry[key];
            }
          });
        }
        written.type = chosen;
        readers.forEach(function (reader) {
          var value = reader.read();
          if (value !== undefined) {
            written[reader.key] = value;
          }
        });
        return written;
      }
    };
  }

  function buildList(kind, entries, types, commonFields, heading, intro, addLabel, blank) {
    var box = element("div");
    var list = element("div");
    var items = entries.slice();
    var readers = [];

    function render() {
      clear(list);
      readers = [];
      items.forEach(function (entry, index) {
        var built = buildEntry(kind, entry, index + 1, types, commonFields, function () {
          items.splice(index, 1);
          render();
        });
        readers.push(built);
        list.appendChild(built.node);
      });
      if (items.length === 0) {
        list.appendChild(element("p", {"class": "help", text: "None yet."}));
      }
    }

    var addButton = element("button", {type: "button", "class": "secondary", text: addLabel});
    addButton.addEventListener("click", function () {
      items = readers.map(function (reader) {
        return reader.read();
      });
      items.push(blank());
      render();
      var last = list.querySelector("fieldset:last-of-type select");
      if (last) {
        last.focus();
      }
    });

    box.appendChild(element("h3", {text: heading}));
    box.appendChild(element("p", {"class": "help", text: intro}));
    box.appendChild(list);
    box.appendChild(element("div", {"class": "actions"}, [addButton]));
    render();

    return {
      node: box,
      read: function () {
        return readers.map(function (reader) {
          return reader.read();
        });
      }
    };
  }

  /* ### The Form ### */

  var formReaders = [];
  var sourcesList = null;
  var outputsList = null;

  function buildForm() {
    var container = byId("form-fields");
    clear(container);
    formReaders = [];
    var values = settings.values || {};

    var groups = {};
    var groupOrder = [];
    schema.globals.forEach(function (field) {
      var name = field.group || "Other settings";
      if (!groups[name]) {
        groups[name] = [];
        groupOrder.push(name);
      }
      groups[name].push(field);
    });

    sourcesList = buildList(
      "source", values.sources || [], schema.sourceTypes, schema.sourceCommon,
      "Sources", "What the build reads. Every source needs a label a reader sees.",
      "Add a source", function () {
        return {type: "web"};
      }
    );
    container.appendChild(sourcesList.node);

    groupOrder.forEach(function (name) {
      var fieldset = element("fieldset", {}, [element("legend", {text: name})]);
      groups[name].forEach(function (field) {
        var built = buildField(field, values[field.key], "global");
        formReaders.push(built);
        fieldset.appendChild(built.node);
      });
      container.appendChild(fieldset);
    });

    outputsList = buildList(
      "output", values.outputs || schema.defaultOutputs, schema.outputTypes, schema.outputCommon,
      "Outputs", "What the build writes under the output folder.",
      "Add an output", function () {
        return {type: "sqlite"};
      }
    );
    container.appendChild(outputsList.node);
  }

  function readForm() {
    var form = {};
    formReaders.forEach(function (reader) {
      var value = reader.read();
      if (value !== undefined) {
        form[reader.key] = value;
      }
    });
    form.sources = sourcesList.read();
    form.outputs = outputsList.read();
    return form;
  }

  /* ### Views ### */

  function showSettings(reason) {
    byId("settings-path").textContent = state.settingsFile;
    byId("settings-docs").href = CONFIGURATION_DOCS;
    var problem = byId("settings-problem");
    if (settings.error) {
      problem.textContent = "A build would refuse this file: " + settings.error;
      problem.hidden = false;
    } else {
      problem.hidden = true;
    }
    byId("settings-text").value = settings.text || "";
    if (settings.values) {
      buildForm();
      byId("show-form").disabled = false;
    } else {
      clear(byId("form-fields"));
      byId("form-fields").appendChild(element("p", {"class": "help",
        text: "The form cannot show this file until its text is valid YAML. Fix it in the advanced view."}));
      byId("show-form").disabled = true;
      switchView("text");
    }
    show("settings");
    if (reason) {
      say(reason);
    }
  }

  function switchView(name) {
    var form = name === "form";
    byId("form-panel").hidden = !form;
    byId("text-panel").hidden = form;
    byId("show-form").setAttribute("aria-pressed", form ? "true" : "false");
    byId("show-text").setAttribute("aria-pressed", form ? "false" : "true");
  }

  function showWelcome() {
    byId("welcome-folder").textContent = state.settingsFolder;
    byId("welcome-docs").href = state.docsUrl;
    updateWelcomeCommand();
    show("welcome");
  }

  function updateWelcomeCommand() {
    var parts = ["extractium init"];
    var name = byId("welcome-name").value.trim();
    var slug = byId("welcome-slug").value.trim();
    var seed = byId("welcome-seed").value.trim();
    if (name) {
      parts.push("--name " + quoted(name));
    }
    if (slug) {
      parts.push("--slug " + quoted(slug));
    }
    if (seed) {
      parts.push("--seed-url " + quoted(seed));
    }
    byId("welcome-command").textContent = parts.join(" ");
  }

  function quoted(text) {
    return /^[A-Za-z0-9_./:@%+=-]+$/.test(text) ? text : '"' + text.replace(/"/g, '\\"') + '"';
  }

  function loadSettings() {
    return api("GET", "/api/settings").then(function (answer) {
      if (answer.status !== 200) {
        throw new Error(answer.body && answer.body.error ? answer.body.error : "The settings could not be read.");
      }
      settings = answer.body;
      schema = answer.body.schema;
      state = answer.body.state;
      byId("version").textContent = state.version;
      byId("footer-docs").href = state.docsUrl;
      return settings;
    });
  }

  function refresh(reason) {
    return loadSettings().then(function () {
      if (settings.exists) {
        showSettings(reason);
      } else {
        showWelcome();
        if (reason) {
          say(reason);
        }
      }
    }).catch(function (error) {
      complain(String(error.message || error));
    });
  }

  /* ### Actions ### */

  function saveForm(event) {
    event.preventDefault();
    var button = byId("save-form");
    busy(button, true);
    api("POST", "/api/settings", {form: readForm()}).then(function (answer) {
      busy(button, false);
      if (answer.status !== 200) {
        complain(answer.body && answer.body.error ? answer.body.error : "The settings could not be saved.");
        return;
      }
      settings = answer.body;
      state = answer.body.state;
      showSettings(answer.body.kept
        ? "Saved. The previous file is kept as " + answer.body.kept + "."
        : "Saved.");
    }).catch(function (error) {
      busy(button, false);
      complain(String(error.message || error));
    });
  }

  function saveText(event) {
    event.preventDefault();
    var button = byId("save-text");
    busy(button, true);
    api("POST", "/api/settings", {text: byId("settings-text").value}).then(function (answer) {
      busy(button, false);
      if (answer.status !== 200) {
        complain(answer.body && answer.body.error ? answer.body.error : "The file could not be saved.");
        return;
      }
      settings = answer.body;
      state = answer.body.state;
      showSettings(answer.body.kept
        ? "Saved. The previous file is kept as " + answer.body.kept + "."
        : "Saved.");
      switchView("text");
    }).catch(function (error) {
      busy(button, false);
      complain(String(error.message || error));
    });
  }

  function writeFirstSettings(event) {
    event.preventDefault();
    var button = byId("welcome-submit");
    busy(button, true);
    var payload = {
      name: byId("welcome-name").value,
      slug: byId("welcome-slug").value,
      seed_url: byId("welcome-seed").value
    };
    api("POST", "/api/welcome", payload).then(function (answer) {
      busy(button, false);
      if (answer.status !== 200) {
        complain(answer.body && answer.body.error ? answer.body.error : "The settings file could not be written.");
        return;
      }
      settings = answer.body;
      state = answer.body.state;
      showSettings("Wrote " + answer.body.path + ". To build, run the build script in that folder; "
        + "every setting can be changed here first.");
    }).catch(function (error) {
      busy(button, false);
      complain(String(error.message || error));
    });
  }

  function quit() {
    if (!window.confirm("Stop the Extractium page? The terminal window will close its server.")) {
      return;
    }
    api("POST", "/api/quit").then(function () {
      stopPinging();
      ["welcome", "settings", "no-token"].forEach(function (id) {
        byId(id).hidden = true;
      });
      say("The page has stopped. You can close this tab. Start it again with extractium ui.");
    }).catch(function () {
      say("The page has stopped. You can close this tab.");
    });
  }

  /* ### Checking In ### */

  function ping() {
    api("GET", "/api/ping").catch(function () {
      // The server has stopped; the next action will say so.
    });
  }

  function startPinging() {
    stopPinging();
    var seconds = state && state.pingSeconds ? state.pingSeconds : 30;
    pingTimer = window.setInterval(ping, seconds * 1000);
  }

  function stopPinging() {
    if (pingTimer !== null) {
      window.clearInterval(pingTimer);
      pingTimer = null;
    }
  }

  /* ### Start ### */

  function start() {
    byId("quit-button").addEventListener("click", quit);
    byId("welcome-form").addEventListener("submit", writeFirstSettings);
    ["welcome-name", "welcome-slug", "welcome-seed"].forEach(function (id) {
      byId(id).addEventListener("input", updateWelcomeCommand);
    });
    byId("settings-form").addEventListener("submit", saveForm);
    byId("text-form").addEventListener("submit", saveText);
    byId("show-form").addEventListener("click", function () {
      switchView("form");
    });
    byId("show-text").addEventListener("click", function () {
      switchView("text");
    });
    byId("reload-form").addEventListener("click", function () {
      refresh("Changes discarded.");
    });
    byId("reload-text").addEventListener("click", function () {
      refresh("Changes discarded.");
    });

    if (!token) {
      show("no-token");
      byId("quit-button").disabled = true;
      return;
    }
    refresh().then(startPinging);
  }

  // Pasting the printed address into a tab that already shows the page
  // changes only the fragment, which does not reload the document, so
  // the page reloads itself to pick the token up.
  window.addEventListener("hashchange", function () {
    if (/(?:^|[#&])token=/.test(window.location.hash)) {
      window.location.reload();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
