<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('admin_action_audits', function (Blueprint $table) {
            $table->id();
            $table->foreignId('actor_user_id')->constrained('users')->restrictOnDelete();
            $table->uuid('request_id')->index();
            $table->string('event', 64);
            $table->string('model_type', 160);
            $table->string('model_key', 160)->nullable();
            $table->json('changed_fields');
            $table->string('route_name', 190)->nullable();
            $table->string('method', 10);
            $table->char('ip_hash', 64)->nullable();
            $table->char('user_agent_hash', 64)->nullable();
            $table->timestamp('created_at')->useCurrent()->index();
        });

        if (DB::getDriverName() === 'sqlite') {
            DB::unprepared("CREATE TRIGGER admin_action_audits_no_update
                BEFORE UPDATE ON admin_action_audits
                BEGIN SELECT RAISE(ABORT, 'admin audit is append-only'); END");
            DB::unprepared("CREATE TRIGGER admin_action_audits_no_delete
                BEFORE DELETE ON admin_action_audits
                BEGIN SELECT RAISE(ABORT, 'admin audit is append-only'); END");
        }
    }

    public function down(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            DB::unprepared('DROP TRIGGER IF EXISTS admin_action_audits_no_update');
            DB::unprepared('DROP TRIGGER IF EXISTS admin_action_audits_no_delete');
        }
        Schema::dropIfExists('admin_action_audits');
    }
};
