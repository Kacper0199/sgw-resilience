import { ApiError } from "@/lib/api";

/** The server's wording ("invalid user id or password") as a sentence: capital first, full stop last, "ID" in capitals. */
const readable = (message: string): string => {
  const text = message.trim().replace(/\bid\b/gi, "ID");
  if (!text) return "Could not sign in. Try again.";
  const sentence = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`;
};

/** The sentence under the form: the server's reason as a sentence, or one line when the server cannot be reached. */
export function loginErrorMessage(error: unknown): string | null {
  if (!error) return null;
  return error instanceof ApiError ? readable(error.message) : "Can't reach SGW. Check your connection.";
}
