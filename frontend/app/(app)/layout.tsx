import { AuthGate } from "@/components/AuthGate";
import { FloatingChat } from "@/components/FloatingChat";
import { Sidebar } from "@/components/Sidebar";

/**
 * Shell for every signed-in page: left navigation, the page itself, and the
 * floating Ask MeetMind panel. AuthGate redirects to /login when there is no
 * valid session, so nothing inside this group renders unauthenticated.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <div className="flex min-h-screen flex-col lg:block lg:pl-[252px]">
        <Sidebar />
        <div className="app-content min-w-0 flex-1">{children}</div>
        <FloatingChat />
      </div>
    </AuthGate>
  );
}
