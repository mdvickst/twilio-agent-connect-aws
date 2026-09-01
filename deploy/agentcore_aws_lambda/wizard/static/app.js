"use strict";

const form = document.getElementById("ivr-form");
const intentList = document.getElementById("intent-list");
const banner = document.getElementById("banner");

/** Turn an intent name into the slug the agent and Studio flow route on. */
function slugify(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 31);
}

function show(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

function clearErrors() {
  form.querySelectorAll(".error").forEach((node) => {
    node.textContent = "";
    node.hidden = true;
  });
  banner.hidden = true;
}

/** Build a destination editor from the shared template. */
function makeDestinationEditor() {
  const fragment = document
    .getElementById("destination-fields")
    .content.cloneNode(true);
  const fieldset = fragment.querySelector("fieldset");
  const groupName = `destinationType-${Math.random().toString(36).slice(2)}`;

  fieldset.querySelectorAll('input[name="destinationType"]').forEach((radio) => {
    radio.name = groupName;
    radio.addEventListener("change", () => {
      fieldset.querySelectorAll("[data-fields]").forEach((block) => {
        block.hidden = block.dataset.fields !== radio.value;
      });
    });
  });

  return fieldset;
}

function selectedType(fieldset) {
  const checked = fieldset.querySelector("input[type=radio]:checked");
  return checked ? checked.value : "phone";
}

function value(fieldset, name) {
  const field = fieldset.querySelector(`[name="${name}"]`);
  return field ? field.value.trim() : "";
}

/** Parse "X-Name: value" lines into an object. Blank lines are ignored. */
function parseHeaders(text) {
  const headers = {};
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const separator = line.indexOf(":");
      if (separator > 0) {
        headers[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
      }
    });
  return headers;
}

/**
 * Read the active destination type's fields.
 *
 * Optional fields are omitted entirely rather than sent as "", so the Pydantic
 * model applies its own defaults instead of rejecting an empty string.
 */
function readDestination(fieldset) {
  const type = selectedType(fieldset);

  if (type === "phone") {
    const destination = { type: "phone", number: value(fieldset, "number") };
    const extension = value(fieldset, "extension");
    if (extension) {
      destination.extension = extension;
      const pause = value(fieldset, "extensionPauseSeconds");
      if (pause) {
        destination.extensionPauseSeconds = Number(pause);
      }
    }
    return destination;
  }

  if (type === "sip") {
    const destination = { type: "sip", uri: value(fieldset, "uri") };
    const headers = parseHeaders(value(fieldset, "headers"));
    if (Object.keys(headers).length) {
      destination.headers = headers;
    }
    const username = value(fieldset, "username");
    const password = value(fieldset, "password");
    if (username) destination.username = username;
    if (password) destination.password = password;
    return destination;
  }

  return { type: "client", identity: value(fieldset, "identity") };
}

function addIntentRow(data) {
  const fragment = document.getElementById("intent-row").content.cloneNode(true);
  const row = fragment.querySelector("li");
  const nameField = row.querySelector('[name="name"]');
  const slugNode = row.querySelector("[data-slug]");
  const editor = makeDestinationEditor();

  row.appendChild(editor);

  nameField.addEventListener("input", () => {
    slugNode.textContent = slugify(nameField.value) || "—";
  });

  row.querySelector(".remove").addEventListener("click", () => {
    row.remove();
    refreshRemoveButtons();
  });

  if (data) {
    nameField.value = data.name || "";
    row.querySelector('[name="description"]').value = data.description || "";
    slugNode.textContent = data.key || slugify(nameField.value) || "—";
    applyDestination(editor, data.destination);
  }

  intentList.appendChild(row);
  refreshRemoveButtons();
  return row;
}

/** Never let the form reach zero intents — the config model requires at least one. */
function refreshRemoveButtons() {
  const rows = intentList.querySelectorAll("li.intent");
  rows.forEach((row) => {
    row.querySelector(".remove").disabled = rows.length <= 1;
  });
}

function applyDestination(fieldset, destination) {
  if (!destination) return;

  const radio = fieldset.querySelector(`input[value="${destination.type}"]`);
  if (radio) {
    radio.checked = true;
    radio.dispatchEvent(new Event("change"));
  }

  const setField = (name, fieldValue) => {
    const field = fieldset.querySelector(`[name="${name}"]`);
    if (field && fieldValue !== undefined && fieldValue !== null) {
      field.value = fieldValue;
    }
  };

  setField("number", destination.number);
  setField("extension", destination.extension);
  setField("extensionPauseSeconds", destination.extensionPauseSeconds);
  setField("uri", destination.uri);
  setField("username", destination.username);
  setField("identity", destination.identity);

  if (destination.headers) {
    setField(
      "headers",
      Object.entries(destination.headers)
        .map(([key, headerValue]) => `${key}: ${headerValue}`)
        .join("\n")
    );
  }
}

function field(name) {
  return form.elements.namedItem(name);
}

function collectConfig() {
  const voice = {};
  const language = field("language").value;
  const voiceName = field("voice").value.trim();
  if (language) voice.language = language;
  if (voiceName) voice.voice = voiceName;

  const numberSelect = field("phoneNumberSid");
  const selectedOption = numberSelect.options[numberSelect.selectedIndex];

  const intents = Array.from(intentList.querySelectorAll("li.intent")).map((row) => {
    const name = row.querySelector('[name="name"]').value.trim();
    return {
      key: slugify(name),
      name,
      description: row.querySelector('[name="description"]').value.trim(),
      destination: readDestination(row.querySelector("fieldset.destination")),
    };
  });

  return {
    version: 1,
    business: {
      name: field("businessName").value.trim(),
      prompt: field("businessPrompt").value.trim(),
      greeting: field("greeting").value.trim(),
    },
    voice,
    intents,
    fallback: {
      name: field("fallbackName").value.trim(),
      description: field("fallbackDescription").value.trim(),
      destination: readDestination(
        document.querySelector("#fallback-destination fieldset.destination")
      ),
    },
    twilio: {
      phoneNumber: selectedOption ? selectedOption.dataset.number : "",
      phoneNumberSid: numberSelect.value,
      conversationConfigurationId: field("conversationConfigurationId").value,
    },
  };
}

function credentialsPayload() {
  return {
    accountSid: field("accountSid").value.trim(),
    authToken: field("authToken").value.trim(),
    apiKey: field("apiKey").value.trim(),
    apiSecret: field("apiSecret").value.trim(),
  };
}

/**
 * Render Pydantic errors next to the field that caused them.
 *
 * `loc` looks like ["body","config","intents",0,"destination","number"]. Anything
 * that cannot be mapped to an input goes to the banner so no error is swallowed.
 */
function showFieldErrors(errors) {
  const unmapped = [];

  errors.forEach((error) => {
    const path = (error.loc || []).filter(
      (part) => part !== "body" && part !== "config"
    );
    const message = error.msg || "Invalid value";

    if (path[0] === "intents" && typeof path[1] === "number") {
      const row = intentList.querySelectorAll("li.intent")[path[1]];
      if (row) {
        const target = path.includes("destination")
          ? row.querySelector('[data-error="destination"]')
          : row.querySelector('[data-error="row"]');
        show(target, `${path.slice(2).join(".")}: ${message}`);
        return;
      }
    }

    if (path[0] === "intents") {
      show(document.getElementById("intents-error"), message);
      return;
    }
    if (path[0] === "business") {
      show(document.getElementById("business-error"), `${path.join(".")}: ${message}`);
      return;
    }
    if (path[0] === "fallback") {
      show(document.getElementById("fallback-error"), `${path.join(".")}: ${message}`);
      return;
    }
    if (path[0] === "twilio") {
      show(document.getElementById("resources-error"), `${path.join(".")}: ${message}`);
      return;
    }
    if (path[0] === "credentials" || path[0] === "aws") {
      show(document.getElementById("credentials-error"), `${path.join(".")}: ${message}`);
      return;
    }

    unmapped.push(`${path.join(".")}: ${message}`);
  });

  if (unmapped.length) {
    show(banner, unmapped.join(" · "));
  }
}

async function testConnection() {
  clearErrors();
  const button = document.getElementById("test-connection");
  button.disabled = true;
  button.textContent = "Checking...";

  try {
    const response = await fetch("/api/resources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentialsPayload()),
    });
    const body = await response.json();

    if (!response.ok) {
      show(
        document.getElementById("credentials-error"),
        typeof body.detail === "string" ? body.detail : "Could not reach Twilio."
      );
      return;
    }

    const numberSelect = field("phoneNumberSid");
    numberSelect.innerHTML = "";
    body.phoneNumbers.forEach((number) => {
      const option = document.createElement("option");
      option.value = number.sid;
      option.dataset.number = number.phoneNumber;
      option.textContent = `${number.phoneNumber} — ${number.friendlyName}`;
      numberSelect.appendChild(option);
    });

    const configSelect = field("conversationConfigurationId");
    configSelect.innerHTML = "";
    body.conversationConfigurations.forEach((configuration) => {
      const option = document.createElement("option");
      option.value = configuration.id;
      option.textContent = `${configuration.displayName} (${configuration.id})`;
      configSelect.appendChild(option);
    });

    if (!body.phoneNumbers.length) {
      show(
        document.getElementById("resources-error"),
        "No voice-capable numbers on this account. Buy one in the Twilio Console first."
      );
    }
    if (!body.conversationConfigurations.length) {
      show(
        document.getElementById("resources-error"),
        "No Conversation Orchestrator configurations found. Create one in the Console first."
      );
    }

    document.getElementById("resources-section").classList.remove("disabled");
    show(document.getElementById("credentials-ok"), `Connected to ${body.accountName}.`);
  } finally {
    button.disabled = false;
    button.textContent = "Test connection";
  }
}

async function save(event) {
  event.preventDefault();
  clearErrors();

  const button = document.getElementById("save");
  button.disabled = true;

  try {
    const response = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        credentials: credentialsPayload(),
        aws: {
          profile: field("awsProfile").value.trim(),
          accountId: field("awsAccountId").value.trim(),
          region: field("awsRegion").value.trim(),
        },
        config: collectConfig(),
      }),
    });

    const body = await response.json();

    if (response.status === 422) {
      showFieldErrors(Array.isArray(body.detail) ? body.detail : []);
      return;
    }
    if (!response.ok) {
      show(banner, typeof body.detail === "string" ? body.detail : "Could not save.");
      return;
    }

    document.getElementById("next-command").textContent = body.nextCommand;
    const list = document.getElementById("written-files");
    list.innerHTML = "";
    body.written.forEach((path) => {
      const item = document.createElement("li");
      item.textContent = path;
      list.appendChild(item);
    });
    document.getElementById("done").hidden = false;
    document.getElementById("done").scrollIntoView({ behavior: "smooth" });
  } finally {
    button.disabled = false;
  }
}

async function restore() {
  const response = await fetch("/api/config");
  const body = await response.json();
  const env = body.env || {};

  if (env.AWS_PROFILE) field("awsProfile").value = env.AWS_PROFILE;
  if (env.AWS_ACCOUNT_ID) field("awsAccountId").value = env.AWS_ACCOUNT_ID;
  if (env.AWS_REGION) field("awsRegion").value = env.AWS_REGION;
  if (env.TWILIO_ACCOUNT_SID) field("accountSid").value = env.TWILIO_ACCOUNT_SID;
  if (env.TWILIO_API_KEY) field("apiKey").value = env.TWILIO_API_KEY;

  ["authToken", "apiSecret"].forEach((name) => {
    const key = name === "authToken" ? "TWILIO_AUTH_TOKEN" : "TWILIO_API_SECRET";
    if (env[key]) {
      field(name).placeholder = `${env[key]} — re-enter to save`;
    }
  });

  const config = body.config;
  if (!config) {
    addIntentRow();
    addIntentRow();
    return;
  }

  field("businessName").value = config.business.name;
  field("businessPrompt").value = config.business.prompt;
  field("greeting").value = config.business.greeting;
  document.getElementById("prompt-count").textContent = String(
    config.business.prompt.length
  );

  if (config.voice && config.voice.language) field("language").value = config.voice.language;
  if (config.voice && config.voice.voice) field("voice").value = config.voice.voice;

  field("fallbackName").value = config.fallback.name;
  field("fallbackDescription").value = config.fallback.description;
  applyDestination(
    document.querySelector("#fallback-destination fieldset.destination"),
    config.fallback.destination
  );

  config.intents.forEach((intent) => addIntentRow(intent));

  const numberSelect = field("phoneNumberSid");
  const option = document.createElement("option");
  option.value = config.twilio.phoneNumberSid;
  option.dataset.number = config.twilio.phoneNumber;
  option.textContent = `${config.twilio.phoneNumber} (saved)`;
  numberSelect.appendChild(option);

  const configSelect = field("conversationConfigurationId");
  const configOption = document.createElement("option");
  configOption.value = config.twilio.conversationConfigurationId;
  configOption.textContent = `${config.twilio.conversationConfigurationId} (saved)`;
  configSelect.appendChild(configOption);

  document.getElementById("resources-section").classList.remove("disabled");
}

document
  .getElementById("fallback-destination")
  .appendChild(makeDestinationEditor());

document.getElementById("add-intent").addEventListener("click", () => addIntentRow());
document.getElementById("test-connection").addEventListener("click", testConnection);
form.addEventListener("submit", save);
field("businessPrompt").addEventListener("input", (event) => {
  document.getElementById("prompt-count").textContent = String(event.target.value.length);
});

restore().catch(() => {
  show(banner, "Could not load existing configuration.");
  addIntentRow();
  addIntentRow();
});
