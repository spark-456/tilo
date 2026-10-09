// WEB-LEGAL: the words of /privacy and /terms, written only from what the repo and the PRD do:
// PRD 6.3 (service map), 6.4/D-14 (region), 15.1 (retention), 16.1/16.5/16.6 (privacy, Google user data),
// 18.4 (Access copy), infra/ACCESS.md, config/connectors.yaml (the scopes) and ADR-0024 (meeting host).
// The page is plain data so the test can read the same text the page shows. TODO comments mark statements the
// repo does not prove; they are not shown on the page.

export type Inline = string | { href: string; text: string };
export type Block = { p: Inline[] } | { ul: Inline[][] };
export interface Section {
  id: string;
  heading: string;
  blocks: Block[];
}
export interface LegalDoc {
  title: string;
  updated: string;
  intro: string;
  sections: Section[];
}

export const CONTACT_EMAIL = "tilotesting@gmail.com";
export const PERMISSIONS_URL = "https://myaccount.google.com/permissions";
export const API_POLICY_URL = "https://developers.google.com/terms/api-services-user-data-policy";

/** The sentence Google's API Services User Data Policy asks every app that uses Google user data to state. */
export const LIMITED_USE =
  "Tilo's use of information received from Google APIs will adhere to the Google API Services User Data Policy, including the Limited Use requirements.";

/** The scopes config/connectors.yaml declares (gmail, google_drive, google_calendar, meeting_host), by their short
 * Google name: the full URL would be read as a backend origin by the deploy guard (tests/repo P0_07c). */
export const SCOPES: { scope: string; what: string }[] = [
  {
    scope: "gmail.readonly",
    what: "Gmail: read and search your messages.",
  },
  {
    scope: "gmail.compose",
    what: "Gmail: save replies as drafts.",
  },
  {
    scope: "gmail.send",
    what: "Gmail: send a reply, after you approve it.",
  },
  {
    scope: "drive.file",
    what: "Google Drive: only the files you pick and the files Tilo creates.",
  },
  {
    scope: "calendar.readonly",
    what: "Google Calendar: read the events on your own calendar.",
  },
  {
    scope: "calendar.events.owned",
    what: "Google Calendar, meeting host only: create meeting invitations.",
  },
];

const mail = { href: `mailto:${CONTACT_EMAIL}`, text: CONTACT_EMAIL };

export const PRIVACY: LegalDoc = {
  title: "Tilo privacy policy",
  updated: "9 October 2026",
  intro:
    "This explains what Tilo does with your information, in plain words. Tilo never sees your password.",
  sections: [
    {
      id: "who",
      heading: "Who runs Tilo",
      blocks: [
        {
          p: [
            "Tilo is a hackathon project built for the Google Cloud AI Builder Cup 2026. It is demo software run by its builders, not a company product. You can reach us at ",
            mail,
            ".",
          ],
        },
      ],
    },
    {
      id: "signin",
      heading: "Signing in",
      blocks: [
        {
          p: [
            "You can sign in with Google, or use an anonymous demo session. Google sign-in is handled by Google, so Tilo never sees your password. An anonymous demo session connects no Google account and gives Tilo no access to your Gmail, Drive or Calendar.",
          ],
        },
      ],
    },
    {
      id: "access",
      heading: "What Tilo can access, and only after you connect it",
      blocks: [
        {
          p: [
            "Tilo reads nothing from your Google account until you connect a connector and approve Google's consent screen. Each connector asks only for the scopes it needs:",
          ],
        },
        {
          ul: [
            [
              "Gmail: Tilo reads your messages to sort replies and saves replies as drafts. It sends a message only after you approve it, or under a rule you set yourself.",
            ],
            [
              "Google Drive: only files you pick and files Tilo creates (the drive.file scope). Tilo cannot see the rest of your Drive.",
            ],
            ["Google Calendar: Tilo reads the events on your own calendar to show them to you."],
            [
              "Meeting host: if you connect it, a separate Google account run by Tilo creates meeting invitations for the people you approve. This is not your own calendar.",
            ],
          ],
        },
        { p: ["The exact scopes are:"] },
        { ul: SCOPES.map((s) => [`${s.scope} (${s.what})`]) },
        {
          p: [
            "Tilo asks for a connector's scopes only when you connect it. You can leave any connector off.",
          ],
        },
      ],
    },
    {
      id: "use",
      heading: "How your information is used",
      blocks: [
        {
          p: [
            "Tilo uses your information only to do the work you ask for, and to show it back to you. Tilo does not sell your data, does not show ads, and does not use your data to train models.",
          ],
        },
        {
          p: [
            // TODO(verify): provider profiles can be overridden; deployed routing and screening are not verified.
            "Tilo calls models through its provider layer. Its default configuration uses Google's models, but other provider profiles can be selected. We have not verified the model routing in a deployed service. Tilo includes Model Armor screening for prompt injection and unsafe content and treats emails, web pages and files as untrusted data.",
          ],
        },
        {
          p: [
            // TODO(verify): confirm deployed recording, analytics and logging settings before a broader content guarantee.
            "Tilo's result cache excludes email bodies. Test recordings can include message content; this is separate from the result cache. We have not verified that all analytics and logs exclude message or file content.",
          ],
        },
      ],
    },
    {
      id: "storage",
      heading: "Where it is stored and how long",
      blocks: [
        {
          p: [
            "Tilo's data is stored on Google Cloud in the asia-southeast1 region (Firestore and Cloud Storage). Your connector tokens are encrypted with Cloud KMS, and only Tilo's connectors service can decrypt them. Requests to Gemini use Google's global endpoint, so the text sent to the model may be processed outside that region.",
          ],
        },
        {
          p: [
            // TODO(verify): PRD 15.1 targets exist in code; automatic purging and complete account deletion are unverified.
            "Tilo's retention targets for saved data are 90 days for tasks, worlds, runs, approval cards and created files; 30 days for live run events and model-call records; and 1 year for the activity ledger and recorded decisions. The code includes secret redaction for model-call records. We have not verified automatic deletion across all stores, so these are targets rather than guaranteed deletion deadlines. Connections and accounts have no automatic age limit in the retention settings; complete deletion after disconnecting or deleting an account is not verified.",
          ],
        },
      ],
    },
    {
      id: "controls",
      heading: "Your controls",
      blocks: [
        {
          ul: [
            [
              "Disconnect any connector in Tilo. Tilo revokes the token at Google and deletes its copy.",
            ],
            [
              "Revoke Tilo's access from your Google account at ",
              { href: PERMISSIONS_URL, text: PERMISSIONS_URL },
              ".",
            ],
            [
              // TODO(verify): verify request handling and erasure across all stores before promising the PRD 16.5 deadline.
              "In-app export and deletion are not available yet. You can ask us to delete your data, or to send you a copy, by emailing ",
              mail,
              ". We cannot yet guarantee deletion from every store within 30 days.",
            ],
          ],
        },
      ],
    },
    {
      id: "google",
      heading: "Google API Services User Data Policy",
      blocks: [
        { p: [LIMITED_USE, " See ", { href: API_POLICY_URL, text: API_POLICY_URL }, "."] },
        {
          p: [
            // TODO(verify): verify all logging paths and staff access controls against the Limited Use requirements.
            "Tilo uses Google user data to provide the features you see in Tilo, not for ads or model training. The Limited Use requirements restrict transfers and human access. We have not verified all logging paths or staff access controls, so we cannot yet guarantee that every path meets those restrictions.",
          ],
        },
      ],
    },
    {
      id: "contact",
      heading: "Contact",
      blocks: [
        {
          p: [
            "Questions or requests: ",
            mail,
            ". Tilo is designed around privacy principles common to major laws, and it has not had a legal review.",
          ],
        },
      ],
    },
  ],
};

export const TERMS: LegalDoc = {
  title: "Tilo terms of use",
  updated: "9 October 2026",
  intro: "By using Tilo you agree to these terms. They are short on purpose.",
  sections: [
    {
      id: "what",
      heading: "What Tilo is",
      blocks: [
        {
          p: [
            "Tilo is demo software built for the Google Cloud AI Builder Cup 2026. It is provided as is, with no warranty of any kind. It may be wrong, slow, changed or switched off at any time, and your data in it may be lost.",
          ],
        },
      ],
    },
    {
      id: "use",
      heading: "Acceptable use",
      blocks: [
        {
          ul: [
            ["Use only accounts and files you are allowed to use."],
            [
              "Do not put confidential employer or client data into this demo, and do not break the law with it.",
            ],
            ["Do not use Tilo to send spam, harass anyone or infringe someone's rights."],
            [
              "Do not try to get around its safety checks, spend limits or approvals, or probe or overload the service.",
            ],
          ],
        },
      ],
    },
    {
      id: "approvals",
      heading: "Approvals are yours",
      blocks: [
        {
          p: [
            "Actions that leave Tilo, such as sending an email, wait for your approval unless you have set a rule that allows them. You are responsible for what you approve and for the rules you set. Check each action before you approve it.",
          ],
        },
      ],
    },
    {
      id: "data",
      heading: "Your data",
      blocks: [
        {
          p: [
            "Your content stays yours. How Tilo handles it is described in the ",
            { href: "/privacy", text: "privacy policy" },
            ".",
          ],
        },
      ],
    },
    {
      id: "liability",
      heading: "Liability",
      blocks: [
        {
          p: [
            // TODO(legal): wording and governing law need legal review before any commercial launch (PRD 16.5); no jurisdiction is named.
            "Tilo is free demo software. These terms have not had a legal review; their enforceability and governing law have not been established. Do not rely on this demo for work where an error or loss of data could cause harm.",
          ],
        },
      ],
    },
    {
      id: "changes",
      heading: "Changes and ending",
      blocks: [
        {
          p: [
            "You can stop using Tilo at any time and disconnect your accounts. We may change these terms or end the service, and we will update this page when we do.",
          ],
        },
      ],
    },
    {
      id: "contact",
      heading: "Contact",
      blocks: [{ p: ["Questions: ", mail, "."] }],
    },
  ],
};
