<?php

namespace Tests\Feature;

use App\Models\User;
use App\Support\AdminAudit;
use Illuminate\Database\QueryException;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class AdminAuditTest extends TestCase
{
    use RefreshDatabase;

    public function test_admin_model_change_is_logged_without_sensitive_values(): void
    {
        $admin = User::factory()->create(['is_admin' => true]);
        $this->actingAs($admin);

        User::factory()->create(['password' => 'not-recorded']);

        $audit = DB::table('admin_action_audits')->sole();
        $fields = json_decode($audit->changed_fields, true, flags: JSON_THROW_ON_ERROR);
        $this->assertSame($admin->id, $audit->actor_user_id);
        $this->assertSame('created', $audit->event);
        $this->assertNotContains('password', $fields);
        $this->assertStringNotContainsString('not-recorded', json_encode($audit));
    }

    public function test_audit_rows_cannot_be_updated_or_deleted(): void
    {
        $admin = User::factory()->create(['is_admin' => true]);
        $this->actingAs($admin);
        User::factory()->create();

        try {
            DB::table('admin_action_audits')->update(['event' => 'forged']);
            $this->fail('Audit update unexpectedly succeeded.');
        } catch (QueryException) {
            $this->assertSame('created', DB::table('admin_action_audits')->value('event'));
        }

        $this->expectException(QueryException::class);
        DB::table('admin_action_audits')->delete();
    }

    public function test_explicit_actions_share_request_id_and_do_not_store_payload_values(): void
    {
        $admin = User::factory()->create(['is_admin' => true]);
        $subject = User::factory()->create();
        $this->actingAs($admin);

        AdminAudit::recordAction('force_payout_attempted', $subject);
        AdminAudit::recordAction('force_payout_succeeded', $subject);

        $audits = DB::table('admin_action_audits')->orderBy('id')->get();
        $this->assertCount(2, $audits);
        $this->assertSame($audits[0]->request_id, $audits[1]->request_id);
        $this->assertSame('[]', $audits[0]->changed_fields);
        $this->assertSame((string) $subject->id, $audits[0]->model_key);
        $this->assertStringNotContainsString('password', json_encode($audits));
    }
}
