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

/** The scopes, exactly as config/connectors.yaml declares them (gmail, google_drive, google_calendar, meeting_host). */
export const SCOPES: { scope: string; what: string }[] = [
  {
    scope: "https://www.googleapis.com/auth/gmail.readonly",
    what: "Gmail: read and search your messages.",
  },
  {
    scope: "https://www.googleapis.com/auth/gmail.compose",
    what: "Gmail: save replies as drafts.",
  },
  {
    scope: "https://www.googleapis.com/auth/gmail.send",
    what: "Gmail: send a reply, after you approve it.",
  },
  {
    scope: "https://www.googleapis.com/auth/drive.file",
    what: "Google Drive: only the files you pick and the files Tilo creates.",
  },
  {
    scope: "https://www.googleapis.com/auth/calendar.readonly",
    what: "Google Calendar: read the events on your own calendar.",
  },
  {
    scope: "https://www.googleapis.com/auth/calendar.events.owned",
    what: "Google Calendar, meeting host only: create meeting invitations.",
  },
];

const mail = { href: `mailto:${CONTACT_EMAIL}`, text: CONTACT_EMAIL };

export const PRIVACY: LegalDoc = {
  title: "Tilo privacy policy",
  updated: "7 October 2026",
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
            // TODO(verify): the sign-in options are PRD 6.3 / infra/ACCESS.md; the web sign-in screen is not mounted yet.
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
            // TODO(verify): config/models.dev.yaml and models.nim.yaml hold dev/test profiles (NVIDIA NIM, fakes); the deployed profile is models.yaml/models.gemini.yaml. Confirm no NIM call carries user data in production.
            "The models that read your content are Google's Gemini models on Vertex AI, called through Tilo's own provider layer. Google Model Armor screens what goes in and out for prompt injection and unsafe content. Tilo treats every email, web page and file as untrusted data, never as instructions.",
          ],
        },
        {
          p: [
            // TODO(verify): "never cached" is PRD 16.5 (Minimise); confirm in services/channels and services/connectors.
            "Tilo does not keep your email bodies in a cache. Analytics, where used, carry no message or file content.",
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
            // TODO(verify): the numbers are the PRD 15.1 defaults; confirm each is enforced in the stores (FR-MEM-09 covers deletion).
            "By default Tilo keeps tasks, worlds, runs, approval cards and the files it creates for 90 days. Live run events are kept for 30 days and the activity ledger for 1 year. Your recorded decisions are kept for 1 year. The record of model calls is kept for 30 days in this demo, with secrets removed. A connection is kept until you disconnect it, and your account until you delete it.",
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
              // TODO(verify): the in-app delete/export (S-22) is not built; the 30-day figure is PRD 16.5.
              "Ask us to delete your data, or to send you a copy, by emailing ",
              mail,
              ". We remove it from every store within 30 days.",
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
            // TODO(verify): the human-access sentence is the policy's own rule; confirm no logging path lets staff read Google data.
            "In practice: Tilo uses Google user data only to provide the features you see in Tilo. It does not transfer that data to others except to provide those features, to follow the law, or as part of a sale of the project. It does not use it for ads or to train models. People on the Tilo team do not read it unless you ask us to, to look into abuse or a security problem, or where the law requires.",
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
  updated: "7 October 2026",
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
            "To the extent the law allows, Tilo's builders are not liable for any loss or damage from using Tilo, including indirect or consequential loss. Tilo is free, and our total liability is limited to what you paid for it, which is nothing.",
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
