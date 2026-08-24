<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class PayoutQueue extends Model
{
    protected $connection = 'exchange';
    protected $table = 'payout_queue';
    public $timestamps = false;

    protected $guarded = ['*'];
}
