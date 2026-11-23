import { Toaster as Sonner, type ToasterProps } from "sonner";

/** Dark pill, bottom centre above the list footer so it never covers the "j k move" hint, 4 s, non-blocking. */
export function Toaster(props: ToasterProps) {
  return (
    <Sonner
      position="bottom-center"
      offset={{ bottom: 56 }}
      mobileOffset={{ bottom: 56 }}
      duration={4000}
      toastOptions={{
        classNames: {
          toast:
            "!rounded-toast !border-0 !bg-toast !text-on-toast !shadow-pop !text-[13px] !font-medium !px-4 !py-3",
          description: "!text-on-toast/80",
          actionButton: "!bg-transparent !text-on-toast !font-semibold !underline",
        },
      }}
      {...props}
    />
  );
}
