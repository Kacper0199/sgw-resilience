import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [
        { text: ["label", "body", "title", "headline", "figure", "display", "page", "section", "reading"] },
      ],
      shadow: [{ shadow: ["pop", "float", "composer", "dialog"] }],
      rounded: [{ rounded: ["toast", "dialog", "composer"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
