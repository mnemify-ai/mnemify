import { AskSettingsForm } from "../../../ask/AskSettingsForm";
import { CompileSettingsSection } from "./CompileSettingsSection";
import { SettingsSection } from "./SettingsSection";

/**
 * AI & Models — the single home for every model decision:
 * the Ask chat engine/model/keys, and the compile engine/models.
 * (Chat settings used to hide inside the chat panel's collapsible footer;
 * compile settings had their own tab.)
 */
export function AiModelsSection() {
  return (
    <div className="max-w-3xl space-y-12">
      <SettingsSection
        eyebrow="Ask"
        title="Chat engine & keys"
        help={
          <>
            The engine and model the Ask dock uses to answer questions over
            your compiled map. Keys are stored in this browser only and sent
            solely to the provider you chose. The composer's model pill is a
            quick-switch for the same settings.
          </>
        }
      >
        <AskSettingsForm />
      </SettingsSection>

      <CompileSettingsSection />
    </div>
  );
}
