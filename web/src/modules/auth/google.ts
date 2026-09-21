interface GoogleCredentialResponse {
  credential?: string;
}

interface GoogleIdentityApi {
  initialize(options: {
    client_id: string;
    callback: (response: GoogleCredentialResponse) => void;
    auto_select: boolean;
    cancel_on_tap_outside: boolean;
    use_fedcm_for_button: boolean;
  }): void;
  renderButton(
    parent: HTMLElement,
    options: {
      type: "standard";
      theme: "outline";
      size: "large";
      text: "continue_with";
      shape: "rectangular";
      logo_alignment: "left";
      width: number;
    },
  ): void;
}

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleIdentityApi } };
  }
}

const scriptId = "google-identity-services";

/** Render Google's supported button flow instead of driving One Tap from a
 * custom click handler. FedCM treats the button click as the required user
 * activation and no longer exposes dependable display-moment callbacks. */
export async function renderGoogleSignInButton(
  host: HTMLElement,
  clientId: string,
  onCredential: (credential: string) => void,
  onError: (message: string) => void,
): Promise<void> {
  const identity = await loadGoogleIdentity();
  identity.initialize({
    client_id: clientId,
    auto_select: false,
    cancel_on_tap_outside: true,
    use_fedcm_for_button: true,
    callback: (response) => {
      if (response.credential) {
        onCredential(response.credential);
        return;
      }
      onError("Google did not return a sign-in credential. Please try again.");
    },
  });
  host.replaceChildren();
  identity.renderButton(host, {
    type: "standard",
    theme: "outline",
    size: "large",
    text: "continue_with",
    shape: "rectangular",
    logo_alignment: "left",
    width: Math.min(400, Math.max(240, Math.floor(host.getBoundingClientRect().width))),
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
