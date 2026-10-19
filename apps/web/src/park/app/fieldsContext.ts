// ADR-0035 L6d (FR-CON-02): where a Park decision gets the fields calls of its own world. `null` offline, in a demo
// session and in tests that inject nothing: such a decision shows no form (nothing to supply there).
import { createContext, useContext } from "react";
import type { FieldsApi } from "../../api/fields";

export type FieldsFor = (worldId: string) => FieldsApi | null;

export const FieldsContext = createContext<FieldsFor | null>(null);
export const useFieldsFor = (): FieldsFor | null => useContext(FieldsContext);
