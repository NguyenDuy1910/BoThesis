interface GoogleCredentialResponse {
  credential?: string;
}

interface GooglePromptNotification {
  isNotDisplayed(): boolean;
  isSkippedMoment(): boolean;
}

interface GoogleIdentityApi {
  initialize(options: {
    client_id: string;
    callback: (response: GoogleCredentialResponse) => void;
    auto_select: boolean;
    cancel_on_tap_outside: boolean;
  }): void;
  prompt(callback?: (notification: GooglePromptNotification) => void): void;
}

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleIdentityApi } };
  }
}

const scriptId = "google-identity-services";

export async function requestGoogleCredential(clientId: string): Promise<string> {
  const identity = await loadGoogleIdentity();
  return new Promise<string>((resolve, reject) => {
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      callback();
    };
    identity.initialize({
      client_id: clientId,
      auto_select: false,
      cancel_on_tap_outside: true,
      callback: (response) => {
        if (response.credential) finish(() => resolve(response.credential!));
        else finish(() => reject(new Error("Google did not return a sign-in credential.")));
      },
    });
    identity.prompt((notification) => {
      if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
        finish(() => reject(new Error("Google sign-in was not completed. Please allow Google sign-in and try again.")));
      }
    });
  });
}

async function loadGoogleIdentity(): Promise<GoogleIdentityApi> {
  const current = window.google?.accounts?.id;
  if (current) return current;
  await new Promise<void>((resolve, reject) => {
    const existing = document.getElementById(scriptId) as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Google sign-in could not be loaded.")), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.id = scriptId;
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Google sign-in could not be loaded."));
    document.head.append(script);
  });
  const identity = window.google?.accounts?.id;
  if (!identity) throw new Error("Google sign-in is unavailable in this browser.");
  return identity;
}
