<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

class WebUser extends Model
{
    protected $connection = 'exchange';
    protected $table = 'web_users';
    public $timestamps = false;

    protected $guarded = ['*'];

    public function supportTickets(): HasMany
    {
        return $this->hasMany(SupportTicket::class, 'web_user_id');
    }
}
