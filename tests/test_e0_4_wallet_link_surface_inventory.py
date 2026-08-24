import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_wallet_linking_has_exact_six_surface_inventory_and_bounded_observation():
    matrix=json.loads((ROOT/"docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    item=next(feature for feature in matrix["features"] if feature["id"]=="EXTERNAL_WALLET_LINKING")
    assert list(item["cells"])==matrix["surfaces"]
    assert item["overallStatus"]=="PARTIAL_NOT_ACCEPTED"
    assert item["moneyWriter"] is False and item["privacySensitiveWriter"] is True
    assert item["authorizationRelevantWriter"] is True
    assert all(item["cells"][name]["mode"]=="REQUIRED" for name in ("telegramBot","site","miniApp","api","native"))
    assert item["cells"]["admin"]["mode"]=="OPERATOR_ONLY"
    assert all(item["cells"][name]["implementation"]=="PARTIAL" for name in ("telegramBot","site","miniApp","api"))
    assert item["cells"]["admin"]["implementation"]==item["cells"]["native"]["implementation"]=="NOT_IMPLEMENTED"
    assert "wallet linking" not in matrix["omittedFeatureFamilies"]
    assert "LUMI advisory" not in matrix["omittedFeatureFamilies"]
    evidence=json.loads((ROOT/"docs/e0-4-wallet-link-runtime-observation.v1.json").read_text())
    for field in ("productionMutation","authenticatedCustomerAction","httpRequestsMade","proofVerificationExercised","walletLinkWriterExercised","walletDisconnectExercised","privateKeyMaterialObserved"):
        assert evidence[field] is False
    assert evidence["acceptance"]=="PARTIAL_NOT_ACCEPTED"
    assert evidence["privacySensitiveWriter"] is True and evidence["authorizationRelevantWriter"] is True
    assert evidence["configuration"]=={"configuredEnvironmentNameObserved":"WALLET_STORE_POSTGRES_ENABLED","configuredValueObserved":True,"configuredEnabled":True}
    assert evidence["telegramBot"]["checkoutMainSha256"]==hashlib.sha256((ROOT/"bot/main_bot.py").read_bytes()).hexdigest()
    assert evidence["relay"]["checkoutMainSha256"]==hashlib.sha256((ROOT/"relay-fastapi/main.py").read_bytes()).hexdigest()
    hashes={"miniApp":"relay/webapp.html","walletLinkCore":"relay/core/wallet_link.py","tonConnectCore":"relay/core/tonconnect.py","signatureProofCore":"relay/core/sig_proof.py","siteProfile":"relay-fastapi/templates/dashboard_profile.html"}
    for name,path in hashes.items():
        assert evidence["artifacts"][name]["deployedAndCheckoutSha256"]==hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    wallet_store=hashlib.sha256((ROOT/"relay/repositories/wallet_store.py").read_bytes()).hexdigest()
    assert evidence["artifacts"]["walletStore"]["checkoutSha256"]==wallet_store
    assert evidence["artifacts"]["walletStore"]["deployedSha256"]!=wallet_store
    deployed={
        "telegramBot":"/opt/obsidian-exchange/bot/main_bot.py",
        "relay":"/opt/obsidian-exchange/relay-fastapi/main.py",
        "miniApp":"/opt/obsidian-exchange/relay/webapp.html",
        "walletLinkCore":"/opt/obsidian-exchange/relay/core/wallet_link.py",
        "tonConnectCore":"/opt/obsidian-exchange/relay/core/tonconnect.py",
        "signatureProofCore":"/opt/obsidian-exchange/relay/core/sig_proof.py",
        "walletStore":"/opt/obsidian-exchange/relay/repositories/wallet_store.py",
        "siteProfile":"/opt/obsidian-exchange/relay-fastapi/templates/dashboard_profile.html",
    }
    assert hashlib.sha256(Path(deployed["telegramBot"]).read_bytes()).hexdigest()==evidence["telegramBot"]["deployedMainSha256"]
    assert hashlib.sha256(Path(deployed["relay"]).read_bytes()).hexdigest()==evidence["relay"]["deployedMainSha256"]
    for name in ("miniApp","walletLinkCore","tonConnectCore","signatureProofCore","siteProfile"):
        assert hashlib.sha256(Path(deployed[name]).read_bytes()).hexdigest()==evidence["artifacts"][name]["deployedAndCheckoutSha256"]
    assert hashlib.sha256(Path(deployed["walletStore"]).read_bytes()).hexdigest()==evidence["artifacts"]["walletStore"]["deployedSha256"]
    db=evidence["database"]
    assert db["totalLinks"]==db["distinctOwners"]==db["distinctChains"]==0
    assert db["byChain"]==[] and db["addressesReturned"] is False and db["userIdentifiersReturned"] is False
    assert [c["name"] for c in db["observedColumns"]]==["user_id","chain","address","verified_at"]
    assert db["primaryKey"]==["user_id","chain"]
    assert set(evidence["negativeSurfaces"])=={"admin","native"}
    provenance=evidence["observationProvenance"]
    assert provenance["observationClass"]=="TIMESTAMPED_READ_ONLY_LOCAL_PRODUCTION_POINT_OBSERVATION"
    assert provenance["continuousVerification"] is False
    assert "no address or user identifier projection" in provenance["databaseQueryShape"]

def test_wallet_link_source_shape_false_success_replay_revoke_and_privacy_gaps_remain_visible():
    main=(ROOT/"relay-fastapi/main.py").read_text()
    core=(ROOT/"relay/core/wallet_link.py").read_text()
    ton=(ROOT/"relay/core/tonconnect.py").read_text()
    store=(ROOT/"relay/repositories/wallet_store.py").read_text()
    schema=(ROOT/"deploy/postgres/014_wallet_store.sql").read_text()
    profile=(ROOT/"relay-fastapi/templates/dashboard_profile.html").read_text()
    ton_verify=main[main.index("async def tonconnect_verify"):main.index("def _proof_subject")]
    generic_verify=main[main.index("async def api_proof_verify"):main.index("async def api_wallet_links")]
    disconnect=main[main.index("async def api_wallet_disconnect"):main.index("async def api_sell_options")]
    assert "_wl.remember" in ton_verify and "if not _wl.remember" not in ton_verify
    assert "_wl.remember" in generic_verify and "if not _wl.remember" not in generic_verify
    assert 'return {"ok": True, "removed": removed}' in disconnect
    assert "except Exception" in core and "return []" in core and "return 0" in core
    assert "check_payload" in ton and "consumed" not in ton.lower()
    assert "ON CONFLICT(user_id,chain) DO UPDATE" in store
    assert "DELETE FROM wallet_links" in store
    assert "revoked_at" not in schema and "proof" not in schema and "audit" not in schema
    proof_message=main[main.index("async def api_proof_message"):main.index("async def api_proof_verify")]
    assert "request.query_params.get('address')" in proof_message
    assert "logger.info(f\"tonconnect verify uid={user['id']}" in main
    assert "logger.info(f\"proof verify uid={uid}" in main
    assert "{{ w.address }}" in profile and "op.counterparty" in profile
    evidence=json.loads((ROOT/"docs/e0-4-wallet-link-runtime-observation.v1.json").read_text())
    assert evidence["artifacts"]["walletStore"]["deployedSQLiteRuntimeDdlPresent"] is True
    assert any("15 minutes" in finding for finding in evidence["riskFindings"])
    assert any("24-hour" in finding for finding in evidence["riskFindings"])
    assert any("reuse RELAY_SECRET" in finding for finding in evidence["riskFindings"])
    assert any("zero links" in finding for finding in evidence["riskFindings"])
    assert {item["disposition"] for item in evidence["independentReviews"]}=={
        "ACCEPTED_PARTIAL_NOT_ACCEPTED", "ACCEPTED_WITH_FINDING_INCORPORATED"}
    failures=evidence["verification"]["knownLegacyFixtureFailures"]
    assert {item["test"] for item in failures}=={"tests/test_wallet_link.py","tests/test_sig_proof.py"}
    assert all(item["result"].startswith("FAIL") for item in failures)
    limits=evidence["verification"]["sourceShapeLimitations"]
    assert any("not a behavioral replay test" in item for item in limits)
    assert any("not injected database-fault tests" in item for item in limits)
