"use client";

import { type FirebaseApp, getApps, initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  getAuth,
  signInWithPopup,
  signOut as firebaseSignOut,
  type Auth,
} from "firebase/auth";

/**
 * Firebase, used for one thing: Google sign-in.
 *
 * The browser signs in with Google, gets an ID token, and hands that to our
 * own API, which verifies it against Google's keys and issues its own
 * session token. Firebase is the identity provider; it is not the database
 * and it is not the session.
 *
 * These values are public on purpose. A Firebase web config is meant to ship
 * in client code — what protects the project is the authorised-domains list
 * and, server-side, verifying the token's signature, audience and issuer.
 */
const config = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
};

/** False when the build has no Firebase config, so the UI can hide the button. */
export const googleSignInAvailable = Boolean(config.apiKey && config.projectId);

let app: FirebaseApp | null = null;

function auth(): Auth {
  if (!googleSignInAvailable) {
    throw new Error("Google sign-in is not configured for this deployment.");
  }
  if (app === null) {
    // getApps() guards against re-initialising across hot reloads.
    app = getApps()[0] ?? initializeApp(config);
  }
  try {
    return getAuth(app);
  } catch (err) {
    // A bad config fails here, before any popup opens, and the message is
    // the only clue as to which value is wrong.
    console.error("[MeetMind] Firebase auth init failed:", err);
    throw new Error(
      `Firebase could not start: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}

/**
 * Open Google's picker and return the ID token for our API to verify.
 *
 * Throws a message worth showing: a popup that the browser blocked and one
 * the user closed are different problems with different fixes.
 */
export async function signInWithGoogle(): Promise<string> {
  const provider = new GoogleAuthProvider();
  // Always show the chooser: people testing with several accounts otherwise
  // get silently signed back into whichever one Google remembers.
  provider.setCustomParameters({ prompt: "select_account" });

  try {
    const result = await signInWithPopup(auth(), provider);
    return await result.user.getIdToken();
  } catch (err) {
    // Log the raw error before interpreting it. Twice now a tidy message has
    // hidden the one detail that would have explained the failure, and a
    // wrong guess costs far more than a noisy console line.
    console.error("[MeetMind] Google sign-in failed:", err);
    const code = (err as { code?: string }).code ?? "";
    if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") {
      throw new Error("Sign-in was cancelled.");
    }
    if (code === "auth/popup-blocked") {
      throw new Error("Your browser blocked the sign-in popup. Allow popups and try again.");
    }
    if (code === "auth/unauthorized-domain") {
      throw new Error(
        "This site is not on the Firebase authorised-domains list. Add it in " +
          "Firebase Console > Authentication > Settings > Authorized domains.",
      );
    }
    if (code === "auth/operation-not-allowed") {
      throw new Error(
        "Google sign-in is not enabled for this Firebase project. Turn it on " +
          "in Firebase Console > Authentication > Sign-in method.",
      );
    }
    if (code === "auth/invalid-api-key" || code === "auth/api-key-not-valid") {
      throw new Error(
        "The Firebase API key is missing or wrong. Check the " +
          "NEXT_PUBLIC_FIREBASE_* values and restart the dev server.",
      );
    }
    if (code === "auth/configuration-not-found") {
      throw new Error(
        "Firebase Authentication is not set up on this project yet. Open " +
          "Firebase Console > Authentication and click Get started.",
      );
    }
    // Anything unrecognised surfaces whatever it does carry. Not every
    // failure here is a FirebaseError with a `code` — if it has only a
    // message, that message is the evidence, so show it rather than
    // replacing it with a sentence that says nothing.
    const detail =
      code || (err instanceof Error && err.message) || String(err ?? "");
    throw new Error(
      detail
        ? `Google sign-in failed: ${detail}`
        : "Google sign-in failed, and the browser gave no reason. Check the " +
          "console for details.",
    );
  }
}

/** Clear the Firebase session. Our own token is cleared separately. */
export async function clearGoogleSession(): Promise<void> {
  if (!googleSignInAvailable || app === null) return;
  try {
    await firebaseSignOut(auth());
  } catch {
    /* Signing out of Google is best-effort; our own session is what matters. */
  }
}
